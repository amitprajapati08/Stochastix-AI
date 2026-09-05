"""
The honest stress test: the model was trained ONLY on V1 attacks
(shared device + shared IP). Now we throw V2 (rotating IP) and V3
(rotating device AND IP) at it — patterns it has never seen — and
measure exactly where recall falls off.

This is not a bug hunt. A drop here is the EXPECTED, correct result:
it tells us precisely which signal the model was actually relying on.
"""
from app.engine import SentinelRedisEngine
from app.model import AsymmetricalSentinelModel
from app.baseline import MerchantLocalBaseline
from app.simulator import BuiltInTrafficSimulator

sim = BuiltInTrafficSimulator(seed=7)
cache_engine = SentinelRedisEngine()
cache_engine.client.flushdb()  # isolate this run from any leftover keys of a previous run
model_engine = AsymmetricalSentinelModel()

# Train on V1 only, same as before
train_pool = []
for _ in range(2000):
    row = cache_engine.extract_realtime_features(sim.generate_legitimate_stream())
    row["is_fraud"] = 0
    train_pool.append(row)
for bot in sim.generate_botnet_burst(scale=200, version=1):
    row = cache_engine.extract_realtime_features(bot)
    row["is_fraud"] = 1
    train_pool.append(row)
model_engine.train_on_simulation_pool(train_pool)

def evaluate_on_version(version: int, scale: int = 60):
    cache_engine.client.flushdb()  # isolate from the previous version's leftover state
    events = [sim.generate_legitimate_stream() for _ in range(200)]
    events += sim.generate_botnet_burst(scale=scale, version=version)

    baseline = MerchantLocalBaseline()
    r = {"baseline": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
         "sentinel": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}}

    for event in events:
        is_fraud = event["is_fraud"]
        b_flag = baseline.score_transaction(event) != "ALLOW"
        features = cache_engine.extract_realtime_features(event)
        _, decision = model_engine.score_transaction(features)
        s_flag = decision != "ALLOW"

        for name, flag in [("baseline", b_flag), ("sentinel", s_flag)]:
            d = r[name]
            if is_fraud and flag: d["tp"] += 1
            elif is_fraud and not flag: d["fn"] += 1
            elif not is_fraud and flag: d["fp"] += 1
            else: d["tn"] += 1

    print(f"\n=== Attack version {version} ===")
    for name in ["baseline", "sentinel"]:
        d = r[name]
        precision = d["tp"] / (d["tp"] + d["fp"]) if (d["tp"] + d["fp"]) else 0.0
        recall = d["tp"] / (d["tp"] + d["fn"]) if (d["tp"] + d["fn"]) else 0.0
        print(f"  {name:9s} TP={d['tp']:3d} FP={d['fp']:3d} FN={d['fn']:3d}  "
              f"Precision={precision:.3f}  Recall={recall:.3f}")

evaluate_on_version(1)
evaluate_on_version(2)
evaluate_on_version(3)
