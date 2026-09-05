# Sentinel — Evaluation Report

Generated: 2026-09-04T20:45:37.489948+00:00

All numbers on this page were produced by `ml/evaluate.py` in this same
run — nothing here is asserted without being measured.

## Headline result: baseline vs Sentinel, by attack sophistication

| Attack version | Baseline recall | Sentinel recall | Sentinel precision |
|---|---|---|---|
| V1 | 5.0% | 98.3% | 100.0% |
| V2 | 10.0% | 98.3% | 100.0% |
| V3 | 0.0% | 0.0% | n/a (no positive predictions made) |

V1 = shared device + shared IP (easy). V2 = shared device, rotating IP.
V3 = rotating device AND IP (hardest — see `docs/failure-recovery.md`
for the honest limitation here).

## Threshold sensitivity (the false-positive cost trade-off)

Cost assumptions (illustrative prototype figures, not Razorpay's real
numbers): false positive costs 800 units, false negative
costs 100 units — an 8x ratio matching the stated
business rule that wrongly blocking a legitimate customer costs far more
than letting one low-value fraud-test transaction through.

| Threshold | Precision | Recall | False Positives | False Negatives | Net Cost |
|---|---|---|---|---|---|
| 0.005 | 99.2% | 99.2% | 1 | 1 | 900 |
| 0.01 | 99.2% | 99.2% | 1 | 1 | 900 |
| 0.03 | 99.2% | 98.3% | 1 | 2 | 1000 |
| 0.05 | 99.2% | 98.3% | 1 | 2 | 1000 |
| 0.1 | 99.2% | 98.3% | 1 | 2 | 1000 |
| 0.3 | 99.2% | 98.3% | 1 | 2 | 1000 |
| 0.5 | 99.2% | 98.3% | 1 | 2 | 1000 |

## Latency benchmark

Measured locally over 500 requests (feature extraction + model scoring):

- p50: 3.193ms
- p95: 4.279ms
- p99: 5.114ms
- SLA budget: 50ms

Measured locally on this machine. Not a claim about Razorpay production infrastructure.

## Training configuration

Held-out validation metrics from training (V1+V2 mixed pool, matching
production bootstrap in `app/main.py`):

- Threshold: 0.5202
- Precision: 1.000
- Recall: 0.983
- False positives: 0
- False negatives: 1
