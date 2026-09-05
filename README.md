# Stochastix AI

**Explainable cross-merchant risk intelligence for coordinated payment abuse.**

Stochastix AI is an inline, real-time card-testing detection prototype:
deterministic Redis sliding-window evidence + an asymmetric-cost LightGBM
risk model + a policy layer + durable audit trail + an incident guardrail.
The interactive dashboard explains what evidence was observed, how the model
score crossed the operating threshold, and why the policy selected ALLOW,
3DS step-up, or BLOCK.

> A payment can look normal in isolation. Stochastix AI asks whether it is
> part of a coordinated attack across merchants.

## Run it

```
redis-server --daemonize yes
pip install -r requirements.txt
python test_pipeline.py          # validates end-to-end, prints held-out metrics + latency
uvicorn app.main:app --reload    # start the API (separate terminal)
streamlit run dashboard.py       # start the explainable dashboard (separate terminal)
```

Set `ANTHROPIC_API_KEY` to get real LLM-generated incident notes from the
agentic guardrail; without it, the guardrail still recalibrates safely and
falls back to a templated note (the safety-critical path never depends on
the LLM call succeeding).

## What was fixed from the original spec

- Asymmetric cost ratio corrected (false positives now cost 8x false
  negatives, matching the stated business rule — the original had this
  backwards).
- Redis keys now expire (TTL) on card/IP/device windows, not just the
  merchant set — the original leaked memory indefinitely.
- ZSET members are now `timestamp:transaction_id` instead of bare
  timestamp, so simultaneous events in the same millisecond aren't
  silently deduped and undercounted.
- The "agentic" layer now actually reasons (LLM-generated incident notes)
  while keeping the safety-critical threshold change itself deterministic
  and bounded (floor/ceiling clamps).
- Fixed a broken API URL in the dashboard (`http://127.0.0` had no port
or path).

## Demo flow

1. **Normal Traffic** — prove that independent customers remain frictionless.
2. **Attack V1** — same device and IP across merchants; show clear linkage.
3. **Attack V2** — rotating IP; show that device and merchant diversity still link the attack.
4. **Attack V3** — rotating device and IP; show the honest coverage boundary and the roadmap for stronger signals.

Run the scenarios in order. The dashboard retains each live API response and
adds a scenario comparison, evidence → risk → policy narrative, network view,
audit lookup, and guardrail log.

## Important prototype boundaries

- Data and labels are synthetic; no real payment or fraud data is used.
- Latency and quality metrics are measured locally, not production claims.
- Cost figures are illustrative prototype assumptions, not real partner figures.
- The agentic layer explains incidents; it never makes a payment decision.

## Continue with another coding assistant

Give the next assistant [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md). It contains the current architecture, API contract, dashboard scope, safe claims, known environment issue, and exact run commands.
