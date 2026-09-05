"""
Day 2 headline experiment.

Same held-out transaction stream, scored two ways:
  1. MerchantLocalBaseline  — sees only what one merchant could see
  2. Sentinel (engine + LightGBM) — sees cross-merchant behavioural signals

This is the actual research question from the spec: does cross-merchant
visibility catch what merchant-local rules structurally cannot?
"""
from app.engine import SentinelRedisEngine
from app.model import AsymmetricalSentinelModel
from app.baseline import MerchantLocalBaseline
from app.simulator import BuiltInTrafficSimulator

sim = BuiltInTrafficSimulator(seed=7)
cache_engine = SentinelRedisEngine()
model_engine = AsymmetricalSentinelModel()

# --- Step 1: build a TRAINING pool (V1 attacks only — the model should
# never have seen V2/V3 during training; that's next week's honest test
# of generalization, not today's) ---
print("Building training pool...")
train_pool = []
for _ in range(2000):
    row = cache_engine.extract_realtime_features(sim.generate_legitimate_stream())
    row["is_fraud"] = 0
    train_pool.append(row)
for bot in sim.generate_botnet_burst(scale=200, version=1):
    row = cache_engine.extract_realtime_features(bot)
    row["is_fraud"] = 1
    train_pool.append(row)

held_out_metrics = model_engine.train_on_simulation_pool(train_pool)
print("\nHeld-out validation (internal to training) metrics:")
for k, v in held_out_metrics.items():
    print(f"  {k}: {v}")

# --- Step 2: build a completely FRESH test stream (new random draws,
# same seeded generator continuing forward) that NEITHER system has
# touched yet, and score it with both systems ---
print("\nBuilding fresh, untouched test stream (V1 attack, mixed with legit)...")
test_events = [sim.generate_legitimate_stream() for _ in range(400)]
test_events += sim.generate_botnet_burst(scale=60, version=1)

baseline = MerchantLocalBaseline()

results = {"baseline": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
           "sentinel": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}}

for event in test_events:
    is_fraud = event["is_fraud"]

    # Baseline sees the raw event only, no Redis features
    baseline_decision = baseline.score_transaction(event)
    baseline_flag = baseline_decision != "ALLOW"

    # Sentinel sees the cross-merchant feature vector
    features = cache_engine.extract_realtime_features(event)
    _, sentinel_decision = model_engine.score_transaction(features)
    sentinel_flag = sentinel_decision != "ALLOW"

    for name, flag in [("baseline", baseline_flag), ("sentinel", sentinel_flag)]:
        r = results[name]
        if is_fraud and flag:
            r["tp"] += 1
        elif is_fraud and not flag:
            r["fn"] += 1
        elif not is_fraud and flag:
            r["fp"] += 1
        else:
            r["tn"] += 1

print("\n=== HEADLINE RESULT: Baseline vs Sentinel on the same test stream ===")
for name in ["baseline", "sentinel"]:
    r = results[name]
    precision = r["tp"] / (r["tp"] + r["fp"]) if (r["tp"] + r["fp"]) else 0.0
    recall = r["tp"] / (r["tp"] + r["fn"]) if (r["tp"] + r["fn"]) else 0.0
    print(f"\n{name.upper()}:")
    print(f"  TP={r['tp']} FP={r['fp']} FN={r['fn']} TN={r['tn']}")
    print(f"  Precision={precision:.3f}  Recall={recall:.3f}")
