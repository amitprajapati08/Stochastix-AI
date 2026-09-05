"""
Standalone validation: proves the pipeline actually works and reports the
honest held-out metrics + measured latency, without needing FastAPI running.
Run: python test_pipeline.py
"""
import time
from app.engine import SentinelRedisEngine
from app.model import AsymmetricalSentinelModel
from app.agent_guard import AgenticRiskGuardrail
from app.simulator import BuiltInTrafficSimulator

cache_engine = SentinelRedisEngine()
model_engine = AsymmetricalSentinelModel()
agent_guard = AgenticRiskGuardrail(model_engine)
sim = BuiltInTrafficSimulator()

print("Building bootstrap training pool...")
pool = []
for _ in range(2000):
    row = cache_engine.extract_realtime_features(sim.generate_legitimate_stream())
    row["is_fraud"] = 0
    pool.append(row)
for bot in sim.generate_botnet_signature_burst(scale=200):
    row = cache_engine.extract_realtime_features(bot)
    row["is_fraud"] = 1
    pool.append(row)

metrics = model_engine.train_on_simulation_pool(pool)
print("\nHeld-out validation metrics at chosen operating threshold:")
for k, v in metrics.items():
    print(f"  {k}: {v}")

print(f"\nOperating threshold selected: {model_engine.optimal_threshold:.4f}")

# --- Live latency test on a fresh burst, simulating the actual inline path ---
print("\nRunning live scoring pass on a fresh legitimate + botnet mix...")
latencies = []
decisions = []
fresh_events = [sim.generate_legitimate_stream() for _ in range(300)] + sim.generate_botnet_signature_burst(scale=40)

for event in fresh_events:
    t0 = time.perf_counter()
    features = cache_engine.extract_realtime_features(event)
    prob, decision = model_engine.score_transaction(features)
    t1 = time.perf_counter()
    latencies.append((t1 - t0) * 1000)
    decisions.append((event["is_fraud"], decision))
    if decision == "BLOCK":
        agent_guard.ingest_webhook_feedback(
            "payment.failed", {"reason": "CARD_TESTING_SUSPECTED", **event}
        )

latencies.sort()
p50 = latencies[len(latencies) // 2]
p95 = latencies[int(len(latencies) * 0.95)]
p99 = latencies[int(len(latencies) * 0.99)]
print(f"  feature+score latency  p50={p50:.3f}ms  p95={p95:.3f}ms  p99={p99:.3f}ms  (SLA budget: 50ms)")

fp = sum(1 for is_fraud, d in decisions if is_fraud == 0 and d != "ALLOW")
fn = sum(1 for is_fraud, d in decisions if is_fraud == 1 and d == "ALLOW")
tp = sum(1 for is_fraud, d in decisions if is_fraud == 1 and d != "ALLOW")
tn = sum(1 for is_fraud, d in decisions if is_fraud == 0 and d == "ALLOW")
print(f"  fresh-batch confusion: TP={tp} FP={fp} FN={fn} TN={tn}")

print(f"\nAgentic guardrail recalibration events fired: {len(agent_guard.incident_log)}")
for inc in agent_guard.incident_log:
    print(f"  -> {inc['note']}")
    print(f"     threshold {inc['old_threshold']:.4f} -> {inc['new_threshold']:.4f}")
