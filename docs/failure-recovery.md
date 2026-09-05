# Failure Recovery Log

Real experiments, documented as they happened. No fabricated failures.

---

## Entry 1: Redis state leaking across separate experiment runs

**Problem:** Re-running the same experiment script twice, with the same
random seed, produced different results (decision threshold 0.0147 vs
0.01 on nominally identical training data).

**Initial approach:** Trusted that a fixed random seed guarantees
reproducibility.

**Observed behaviour:** `redis-cli DBSIZE` showed 10,947 keys still live
in Redis after a full day of running separate scripts — far more than any
single run should produce.

**Root cause:** The simulator's RNG resets fresh every script run, but
Redis key TTLs are 120 seconds, and scripts were being run back-to-back
well within that window. Feature extraction for a "fresh" run was quietly
reading leftover velocity counters from the previous run.

**Fix:** `cache_engine.client.flushdb()` at the start of every standalone
experiment script, and again between evaluating different attack versions
within the same script, so each measurement is genuinely isolated.

**New result:** Threshold and evaluation numbers became stable and
reproducible across repeated runs of the same script.

---

## Entry 2: Model trained on V1 attacks failed completely on V2 (rotating IP)

**Problem:** A model trained only on V1 card-testing attacks (shared
device AND shared IP) achieved 98.3% recall on held-out V1 traffic, but
**0% recall** on V2 attacks (same device, IP rotates per transaction) —
despite the device-based features behaving identically in both cases.

**Initial approach:** Assumed the drop meant the device/merchant-spread
signal itself was too weak and would need to be redesigned.

**Observed behaviour:** Raw feature values (`merchant_diversity_device`,
`velocity_60s_device`) climbed exactly as expected during a V2 attack.
But the model's predicted probability plateaued at 0.0117 — just under
the 0.01472 decision threshold — no matter how high those features rose.

**Root cause:** In the V1-only training data, `velocity_60s_ip` and
`merchant_diversity_device` were perfectly correlated (every attack
shared both device and IP). The model learned an implicit joint
dependency on both firing together, using IP velocity as an unnecessary
confirming signal it never had to separate from device behaviour. When
IP rotation broke that correlation in V2, the confirming signal
disappeared and the score could no longer cross the threshold — even
though the genuinely useful signal (device/merchant spread) was present
the whole time.

**Fix:** Retrained on a mix of V1 and V2 attacks (100 of each) instead of
V1 alone, forcing the model to learn that merchant/device spread matters
independent of IP behaviour.

**New result:**

| | V1 | V2 | V3 (rotating IP + device) |
|---|---|---|---|
| Before fix (V1-only training) | 98.3% recall | 0% recall | 0% recall |
| After fix (V1+V2 training) | 98.3% recall | 96.7% recall | 10% recall |

Precision stayed at 1.0 throughout — the fix cost nothing in false
positives.

**Known limitation, stated honestly:** V3 attacks (rotating both device
and IP) remain largely undetected by identity-based features, since there
is no shared identity left for velocity/diversity counters to latch onto.
Catching V3 would need a different signal class entirely — likely
amount-pattern or timing-pattern fingerprinting — which is genuine future
work, not something to claim as solved.



---

## Entry 4: merchant_diversity_device wasn't a real 60-second rolling window

**Problem:** The dominant risk feature (by a wide margin in feature
importance) used a plain Redis SET with a whole-key TTL to track
distinct merchants per device. Individual merchants never aged out —
the count could grow unbounded for as long as a device stayed active,
not reset on a genuine 60-second window like the velocity features.

**Initial approach:** Trusted that "it has a TTL" meant "it's windowed
correctly," without checking that a SET's TTL applies to the whole key,
not to individual members.

**Observed behaviour:** Reproduced the exact old logic in isolation:
added merchant_A, then merchant_B, waited past the test window, added
merchant_C — count was 3, not 1. Confirmed the defect directly.

**Root cause:** A SET has no per-member timestamp, so it structurally
cannot implement a rolling window on its own members — only on the key
as a whole.

**Fix:** Replaced the SET with a sorted set (ZSET) keyed by merchant_id,
score = last-seen timestamp — the same correct pattern already used for
velocity — with `ZREMRANGEBYSCORE` evicting stale entries before every count.

**New result:** Two new unit tests (`tests/test_engine.py`) prove
correct eviction. Full evaluation suite re-run: precision 1.000, recall
0.983 — identical to before, because every existing test/demo completed
well within the old 120s TTL, so the defect never actually triggered in
results reported so far. This is a real correctness fix for longer
sessions (a live demo, or production) — not a fix that changes today's
numbers, and it's reported that way rather than overclaimed.