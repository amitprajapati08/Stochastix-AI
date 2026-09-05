# Stochastix AI — Project Handoff

## Product in one sentence

Stochastix AI is an explainable, real-time risk intelligence prototype that detects coordinated card-testing patterns across merchants before an individual merchant can see the whole attack.

## Current state

- The original project name was **Razorpay Sentinel**. The user-facing brand is now **Stochastix AI**.
- Project root: `C:\Dev\razorpay-sentinel`.
- The core detection system is working and should not be rewritten for UI work.
- The dashboard is `dashboard.py`; run it only after the FastAPI backend is running.
- The local `.venv` is currently broken because its Python 3.11 base executable was removed. This blocks test execution until Python and the environment are restored.

## Architecture

```text
Simulator transaction
  -> FastAPI interceptor (app/main.py)
  -> Redis 60-second feature window (app/engine.py)
  -> LightGBM risk model + cost-aware threshold (app/model.py)
  -> policy: ALLOW / 3DS_STEP_UP / BLOCK (app/policy.py)
  -> durable SQLite audit trail (app/audit_db.py)
  -> incident guardrail and optional LLM note (app/agent_guard.py)
```

## Real API contract used by the dashboard

`POST /api/v1/stochastix/intercept` returns a decision, risk score, latency, and `active_metrics_snapshot` containing `amount`, `velocity_60s_card`, `velocity_60s_ip`, `velocity_60s_device`, and `merchant_diversity_device`. The prior `/api/v1/sentinel/intercept` route remains as a deprecated compatibility alias.

The dashboard must use that snapshot for explanations. Do not claim SHAP values, model coefficients, or causal feature contributions—the API exposes observed evidence, not model attribution.

## Simulator scenarios

1. **Normal Traffic:** independent legitimate payments; expected low linkage and mostly ALLOW.
2. **Attack V1:** one shared device and shared IP spread across merchants; easy detection case.
3. **Attack V2:** shared device but rotating IP; device velocity and merchant diversity remain useful.
4. **Attack V3:** rotating device and IP; identity linkage disappears. This is an intentional, documented coverage boundary. Do not frame it as success.

## Dashboard shipped in this workspace

- Four live simulator buttons, reset, and a progress-based demo conductor.
- Scenario-specific explanation cards and attack-evolution narrative.
- Live metrics, evidence bands, score/threshold/policy reasoning, risk trace, and cross-merchant network view.
- Scenario comparison, financial impact assumptions, audit lookup, and incident log.
- Explanation boundaries to avoid overclaiming model interpretability.

## Safe claims

- Precision/recall and latency are locally measured synthetic-simulation results.
- Cost values are illustrative prototype assumptions, never Razorpay production values.
- Data is synthetic and labels are simulator-defined, not real fraud data.
- The agentic layer summarizes an incident but never controls a payment decision.
- V3 needs richer future signals such as behavioural biometrics, authentication context, or network intelligence.

## Restore and run locally

Install Python 3.11, then run:

```powershell
cd C:\Dev\razorpay-sentinel
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
redis-server
```

In two further terminals, run `uvicorn app.main:app --reload` and `streamlit run dashboard.py`. Then validate with `python test_pipeline.py` and `python -m pytest -q`.

## Next work only after the environment is restored

Run each dashboard scenario from a clean reset and verify evidence, decision route, chart, and network view agree. Do not modify the core feature/model/policy behaviour merely to make the demo look better.
