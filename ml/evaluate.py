"""
The full evaluation report. Run this once and it produces the actual
evidence for the Razorpay Buildathon submission: baseline vs Sentinel,
across all 3 attack sophistication levels, a threshold-sensitivity
table, a cost table, and a real latency benchmark.

Nothing in this file is claimed without being measured in this same run.

Usage:
    python ml/evaluate.py
Produces:
    docs/evaluation-report.md   <- the human-readable report
    docs/evaluation-results.json <- raw numbers, for anyone who wants to verify
"""
import json
import time
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import SentinelRedisEngine
from app.model import AsymmetricalSentinelModel, FALSE_POSITIVE_COST, FALSE_NEGATIVE_COST
from app.baseline import MerchantLocalBaseline
from app.simulator import BuiltInTrafficSimulator

RESULTS = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

print("=" * 70)
print("SENTINEL — FULL EVALUATION REPORT")
print("=" * 70)

sim = BuiltInTrafficSimulator(seed=99)
cache = SentinelRedisEngine()
cache.client.flushdb()
model = AsymmetricalSentinelModel()

print("\n[1/5] Training on mixed V1+V2 attack pool (matches production bootstrap)...")
pool = []
for _ in range(2000):
    row = cache.extract_realtime_features(sim.generate_legitimate_stream())
    row["is_fraud"] = 0
    pool.append(row)
for bot in sim.generate_botnet_burst(scale=100, version=1):
    row = cache.extract_realtime_features(bot)
    row["is_fraud"] = 1
    pool.append(row)
for bot in sim.generate_botnet_burst(scale=100, version=2):
    row = cache.extract_realtime_features(bot)
    row["is_fraud"] = 1
    pool.append(row)

held_out_metrics = model.train_on_simulation_pool(pool)
RESULTS["held_out_training_metrics"] = held_out_metrics
RESULTS["cost_assumptions"] = {
    "false_positive_cost_inr_units": FALSE_POSITIVE_COST,
    "false_negative_cost_inr_units": FALSE_NEGATIVE_COST,
    "note": "Illustrative prototype assumptions, not Razorpay's real financial figures.",
}
print(f"  Held-out threshold: {held_out_metrics['threshold']:.4f}")
print(f"  Held-out precision: {held_out_metrics['precision']:.3f}  recall: {held_out_metrics['recall']:.3f}")

print("\n[2/5] Baseline vs Sentinel across attack versions 1, 2, 3...")

def evaluate_version(version: int, scale: int = 60, legit_n: int = 200):
    cache.client.flushdb()
    events = [sim.generate_legitimate_stream() for _ in range(legit_n)]
    events += sim.generate_botnet_burst(scale=scale, version=version)

    baseline = MerchantLocalBaseline()
    r = {"baseline": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
         "sentinel": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}}

    for event in events:
        is_fraud = event["is_fraud"]
        b_flag = baseline.score_transaction(event) != "ALLOW"
        features = cache.extract_realtime_features(event)
        _, decision = model.score_transaction(features)
        s_flag = decision != "ALLOW"

        for name, flag in [("baseline", b_flag), ("sentinel", s_flag)]:
            d = r[name]
            if is_fraud and flag: d["tp"] += 1
            elif is_fraud and not flag: d["fn"] += 1
            elif not is_fraud and flag: d["fp"] += 1
            else: d["tn"] += 1

    out = {}
    for name in ["baseline", "sentinel"]:
        d = r[name]
        precision = d["tp"] / (d["tp"] + d["fp"]) if (d["tp"] + d["fp"]) else None
        recall = d["tp"] / (d["tp"] + d["fn"]) if (d["tp"] + d["fn"]) else None
        out[name] = {**d, "precision": precision, "recall": recall}
    return out

version_results = {}
for v in [1, 2, 3]:
    res = evaluate_version(v)
    version_results[f"v{v}"] = res
    b_recall = res['baseline']['recall']
    s_recall = res['sentinel']['recall']
    s_precision = res['sentinel']['precision']
    print(f"  V{v}: baseline recall={b_recall:.3f}  "
          f"sentinel recall={s_recall:.3f}  "
          f"(sentinel precision={'n/a (no positive predictions)' if s_precision is None else f'{s_precision:.3f}'})")

RESULTS["baseline_vs_sentinel_by_version"] = version_results

print("\n[3/5] Threshold sensitivity sweep...")
cache.client.flushdb()
sweep_events = [sim.generate_legitimate_stream() for _ in range(300)]
sweep_events += sim.generate_botnet_burst(scale=80, version=1)
sweep_events += sim.generate_botnet_burst(scale=40, version=2)

sweep_features = []
sweep_labels = []
for e in sweep_events:
    f = cache.extract_realtime_features(e)
    sweep_features.append(f)
    sweep_labels.append(e["is_fraud"])

import pandas as pd
X_sweep = pd.DataFrame(sweep_features)[["amount","velocity_60s_card","velocity_60s_ip","velocity_60s_device","merchant_diversity_device"]]
probs = model.model.predict(X_sweep)

threshold_table = []
for t in [0.005, 0.01, 0.03, 0.05, 0.1, 0.3, 0.5]:
    decisions = (probs >= t).astype(int)
    tp = int(((decisions == 1) & (pd.Series(sweep_labels) == 1)).sum())
    fp = int(((decisions == 1) & (pd.Series(sweep_labels) == 0)).sum())
    fn = int(((decisions == 0) & (pd.Series(sweep_labels) == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    net_cost = fp * FALSE_POSITIVE_COST + fn * FALSE_NEGATIVE_COST
    threshold_table.append({
        "threshold": t, "precision": round(precision, 3), "recall": round(recall, 3),
        "false_positives": fp, "false_negatives": fn, "net_cost_inr_units": net_cost,
    })
    print(f"  t={t:<6} precision={precision:.3f} recall={recall:.3f} net_cost={net_cost}")

RESULTS["threshold_sensitivity_table"] = threshold_table

print("\n[4/5] Latency benchmark (500 requests)...")
cache.client.flushdb()
latencies = []
bench_events = [sim.generate_legitimate_stream() for _ in range(450)]
bench_events += sim.generate_botnet_burst(scale=50, version=1)

for e in bench_events:
    t0 = time.perf_counter()
    f = cache.extract_realtime_features(e)
    model.score_transaction(f)
    t1 = time.perf_counter()
    latencies.append((t1 - t0) * 1000)

latencies.sort()
n = len(latencies)
latency_stats = {
    "p50_ms": round(latencies[n // 2], 3),
    "p95_ms": round(latencies[int(n * 0.95)], 3),
    "p99_ms": round(latencies[int(n * 0.99)], 3),
    "sla_budget_ms": 50,
    "note": "Measured locally on this machine. Not a claim about Razorpay production infrastructure.",
}
RESULTS["latency_benchmark"] = latency_stats
print(f"  p50={latency_stats['p50_ms']}ms  p95={latency_stats['p95_ms']}ms  p99={latency_stats['p99_ms']}ms")

print("\n[5/5] Writing report...")

docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
os.makedirs(docs_dir, exist_ok=True)

with open(os.path.join(docs_dir, "evaluation-results.json"), "w") as f:
    json.dump(RESULTS, f, indent=2)

md = f"""# Sentinel — Evaluation Report

Generated: {RESULTS['generated_at']}

All numbers on this page were produced by `ml/evaluate.py` in this same
run — nothing here is asserted without being measured.

## Headline result: baseline vs Sentinel, by attack sophistication

| Attack version | Baseline recall | Sentinel recall | Sentinel precision |
|---|---|---|---|
"""
for v in [1, 2, 3]:
    r = version_results[f"v{v}"]
    b_recall_str = f"{r['baseline']['recall']:.1%}" if r['baseline']['recall'] is not None else "n/a"
    s_recall_str = f"{r['sentinel']['recall']:.1%}" if r['sentinel']['recall'] is not None else "n/a"
    s_prec_str = f"{r['sentinel']['precision']:.1%}" if r['sentinel']['precision'] is not None else "n/a (no positive predictions made)"
    md += f"| V{v} | {b_recall_str} | {s_recall_str} | {s_prec_str} |\n"

md += f"""
V1 = shared device + shared IP (easy). V2 = shared device, rotating IP.
V3 = rotating device AND IP (hardest — see `docs/failure-recovery.md`
for the honest limitation here).

## Threshold sensitivity (the false-positive cost trade-off)

Cost assumptions (illustrative prototype figures, not Razorpay's real
numbers): false positive costs {FALSE_POSITIVE_COST} units, false negative
costs {FALSE_NEGATIVE_COST} units — an {FALSE_POSITIVE_COST // FALSE_NEGATIVE_COST}x ratio matching the stated
business rule that wrongly blocking a legitimate customer costs far more
than letting one low-value fraud-test transaction through.

| Threshold | Precision | Recall | False Positives | False Negatives | Net Cost |
|---|---|---|---|---|---|
"""
for row in threshold_table:
    md += f"| {row['threshold']} | {row['precision']:.1%} | {row['recall']:.1%} | {row['false_positives']} | {row['false_negatives']} | {row['net_cost_inr_units']} |\n"

md += f"""
## Latency benchmark

Measured locally over 500 requests (feature extraction + model scoring):

- p50: {latency_stats['p50_ms']}ms
- p95: {latency_stats['p95_ms']}ms
- p99: {latency_stats['p99_ms']}ms
- SLA budget: {latency_stats['sla_budget_ms']}ms

{latency_stats['note']}

## Training configuration

Held-out validation metrics from training (V1+V2 mixed pool, matching
production bootstrap in `app/main.py`):

- Threshold: {held_out_metrics['threshold']:.4f}
- Precision: {held_out_metrics['precision']:.3f}
- Recall: {held_out_metrics['recall']:.3f}
- False positives: {held_out_metrics['false_positives']}
- False negatives: {held_out_metrics['false_negatives']}
"""

with open(os.path.join(docs_dir, "evaluation-report.md"), "w") as f:
    f.write(md)

print(f"\nWrote docs/evaluation-report.md and docs/evaluation-results.json")
print("=" * 70)