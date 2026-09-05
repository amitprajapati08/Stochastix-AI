import time
import logging
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException
from pydantic import BaseModel

from app.engine import SentinelRedisEngine
from app.model import AsymmetricalSentinelModel
from app.agent_guard import AgenticRiskGuardrail
from app.simulator import BuiltInTrafficSimulator
from app import audit_db
from app.schemas import TransactionRequestSchema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel.main")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: bring up Redis connection, bootstrap-train the model on
    # synthetic traffic, wire the agentic guardrail. Bootstrap metrics are
    # printed and stored so they're available on /metrics for the demo and
    # the pitch deck — this IS the "measured precision/recall on a held-out
    # test set" the track asks for, not a number quoted from memory.
    audit_db.init_db()  # durable audit trail — survives restarts, unlike Redis
    cache_engine = SentinelRedisEngine()
    cache_engine.client.flushdb()  # isolate this boot from any leftover dev-session state
    model_engine = AsymmetricalSentinelModel()
    agent_guard = AgenticRiskGuardrail(model_engine)
    traffic_generator = BuiltInTrafficSimulator()

    # Trained on a MIX of attack versions (see docs/failure-recovery.md
    # Entry 2) — training on V1 alone taught the model an implicit
    # dependency on shared-IP velocity that collapsed the moment an
    # attacker rotated IPs.
    bootstrap_pool = []
    for _ in range(2000):
        bootstrap_pool.append(
            cache_engine.extract_realtime_features(traffic_generator.generate_legitimate_stream())
        )
    for bot_payload in traffic_generator.generate_botnet_burst(scale=100, version=1):
        bootstrap_pool.append(cache_engine.extract_realtime_features(bot_payload))
    for bot_payload in traffic_generator.generate_botnet_burst(scale=100, version=2):
        bootstrap_pool.append(cache_engine.extract_realtime_features(bot_payload))

    for row, source in zip(bootstrap_pool, ["legit"] * 2000 + ["bot"] * 200):
        row["is_fraud"] = 1 if source == "bot" else 0

    held_out_metrics = model_engine.train_on_simulation_pool(bootstrap_pool)
    logger.info("Bootstrap held-out metrics: %s", held_out_metrics)

    state["cache_engine"] = cache_engine
    state["model_engine"] = model_engine
    state["agent_guard"] = agent_guard
    state["traffic_generator"] = traffic_generator
    state["held_out_metrics"] = held_out_metrics

    yield
    state.clear()


app = FastAPI(title="Stochastix AI — Cross-Merchant Risk Intelligence API", lifespan=lifespan)


@app.get("/metrics")
def get_held_out_metrics():
    """Held-out validation metrics from the bootstrap training run, and the
    live decision threshold currently in effect (which may have moved since
    bootstrap if the adaptive guardrail has fired)."""
    return {
        "held_out_metrics": state.get("held_out_metrics"),
        "live_threshold": state["model_engine"].optimal_threshold,
        "recalibration_events": len(state["agent_guard"].incident_log),
    }


@app.get("/incidents")
def get_incident_log():
    return state["agent_guard"].incident_log


@app.post("/api/v1/stochastix/intercept")
@app.post("/api/v1/sentinel/intercept", deprecated=True)
def intercept_payment_flow(payload: TransactionRequestSchema, response: Response):
    start_profiling = time.perf_counter()
    input_payload = payload.model_dump()

    try:
        extracted_features = state["cache_engine"].extract_realtime_features(input_payload)
        risk_probability, decision_route = state["model_engine"].score_transaction(extracted_features)

        if decision_route == "BLOCK":
            state["agent_guard"].ingest_webhook_feedback(
                "payment.failed", {"reason": "CARD_TESTING_SUSPECTED", **input_payload}
            )

        total_latency_ms = (time.perf_counter() - start_profiling) * 1000
        response.headers["X-Risk-Engine-Latency"] = f"{total_latency_ms:.3f}ms"

        # Durable write, AFTER the decision is made — never let the audit
        # trail block, delay, OR CRASH the actual authorization response.
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            with audit_db.get_conn() as conn:
                audit_db.record_transaction_and_decision(
                    conn, input_payload, risk_probability, decision_route,
                    state["model_engine"].optimal_threshold, total_latency_ms, now,
                )
        except Exception as audit_error:
            logger.warning("Audit write failed for %s (decision still returned): %s",
                           payload.transaction_id, audit_error)

        return {
            "transaction_id": payload.transaction_id,
            "decision": decision_route,
            "risk_score": round(risk_probability, 5),
            "calculated_latency_ms": f"{total_latency_ms:.3f}ms",
            "active_metrics_snapshot": extracted_features,
        }
    except Exception as network_error:
        raise HTTPException(status_code=500, detail=str(network_error))


@app.get("/audit/{transaction_id}")
def get_audit_trail(transaction_id: str):
    """The literal, demoable answer to 'show me your audit trail' —
    not a claim in a pitch deck, a real query against a real record."""
    with audit_db.get_conn() as conn:
        row = conn.execute(
            "SELECT t.transaction_id, t.timestamp, t.merchant_id, t.amount, "
            "r.risk_probability, r.decision, r.threshold_at_time, r.latency_ms "
            "FROM transactions t JOIN risk_decisions r ON r.transaction_id = t.transaction_id "
            "WHERE t.transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Transaction not found in audit trail")

        incident = conn.execute(
            "SELECT i.incident_id, i.triggered_at, i.note FROM incidents i "
            "JOIN incident_transactions it ON it.incident_id = i.incident_id "
            "WHERE it.transaction_id = ?",
            (transaction_id,),
        ).fetchone()

        return {
            "transaction_id": row[0],
            "timestamp": row[1],
            "merchant_id": row[2],
            "amount": row[3],
            "risk_probability": row[4],
            "decision": row[5],
            "threshold_at_decision_time": row[6],
            "latency_ms": row[7],
            "linked_incident": {
                "incident_id": incident[0],
                "triggered_at": incident[1],
                "note": incident[2],
            } if incident else None,
        }
