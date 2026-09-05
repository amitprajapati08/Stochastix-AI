# Stochastix AI — Technical Specification

Status: draft for review. Scope deliberately cut down from the original
proposal to fit the real time budget — see "Cuts from original scope" at
the end before objecting to anything missing.

## 1. Final problem statement

A payment platform that serves many merchants can see something no single
merchant can: the same device, IP, or card touching many different
merchants in a short window. Coordinated card-testing attacks exploit this
blind spot by fragmenting small validation transactions across merchants
so no individual merchant's fraud system notices. Stochastix AI detects this
cross-merchant pattern in real time, at the pre-authorization step,
without adding meaningful latency to legitimate checkouts.

## 2. Product definition

An inline risk-scoring service (API) that sits in the authorization path,
plus an operations dashboard for a risk analyst to watch live traffic,
trigger a simulated attack, and see the system detect and respond to it.
A stretch component (Section 17) adds an LLM-based investigator that
writes a human-readable incident summary once a high-risk cluster is
flagged — it explains, it does not decide.

## 3. Persona

Primary: a risk operations analyst watching the dashboard during an
active incident, deciding whether to escalate.
Secondary: an engineering reviewer (Razorpay judge) assessing whether the
detection logic, metrics, and latency claims are honest and defensible.

## 4. Core workflow

```
Transaction arrives
  -> deterministic feature extraction (Redis)
  -> ML risk scoring (LightGBM)
  -> policy decision (ALLOW / STEP-UP / BLOCK)
  -> if BLOCK-tier event: added to incident buffer
  -> if incident buffer crosses trigger count: adaptive threshold
     recalibration (deterministic, bounded) + optional AI investigator note
  -> audit log entry written for every decision
```

## 5. System architecture

Deliberately simple — three components, no message queue, no
orchestration layer, no vector/graph database:

- **API gateway (FastAPI)**: receives transactions, calls the feature
  engine and model in-process, returns a decision. This is the
  latency-critical path.
- **Feature store (Redis)**: sliding-window counters and set cardinalities.
  Chosen because it's the simplest thing that gives sub-5ms rolling-window
  reads/writes — not because it's fashionable.
- **Dashboard (Streamlit)**: reads from the API's `/metrics` and
  `/incidents` endpoints, drives the attack simulation button.

Explicitly rejected: Kafka (no streaming-scale requirement at prototype
size), Kubernetes (single process is enough to demonstrate the idea),
vector databases (no semantic search need), graph databases (a handful of
Redis sets already gives us "distinct merchants per device" without a
graph engine — see Section 8).

## 6. Component responsibilities

| File | Responsibility |
|---|---|
| `app/main.py` | API endpoints, request orchestration, startup bootstrap |
| `app/engine.py` | Redis-backed deterministic feature extraction |
| `app/model.py` | LightGBM training, threshold selection, scoring |
| `app/policy.py` | Maps risk score -> ALLOW/STEP-UP/BLOCK, adaptive threshold bounds |
| `app/simulator.py` | Reproducible synthetic traffic + attack generator |
| `app/investigator/` | (Stretch) evidence-grounded LLM incident notes |
| `ml/train.py`, `ml/evaluate.py` | Offline training + evaluation report generation |
| `tests/` | Unit tests for feature engine correctness and policy thresholds |
| `docs/decisions.md` | Running log of real design decisions and why |
| `docs/failure-recovery.md` | The 3 real experiments (Section 20), documented as they happen |

## 7. Transaction schema

```
transaction_id: str
timestamp_ms: int
merchant_id: str
amount: float
currency: str  (fixed "INR" for prototype)
card_token: str        (already tokenized, never a real PAN)
card_bin: str
device_fingerprint: str
ip_address: str
payment_method: str    (card / upi — card-testing is card-specific, keep both for realism)
is_fraud: int           (0/1, SYNTHETIC LABEL from the simulator only — never claim this is ground truth from a real system)
```

## 8. Feature list — deterministic vs ML

**Deterministic (exact counts, no prediction, computed in Redis):**
- transactions per device, last 60s
- transactions per IP, last 60s
- distinct merchants per device, last 60s
- distinct merchants per IP, last 60s
- distinct cards per device, last 60s
- time since this device's previous transaction

**Fed to the model as raw input (not "computed", just passed through):**
- transaction amount

**Deliberately cut from the original feature list** (see Section 26):
merchant-specific baseline deviation, burstiness/variance, decline ratio
(would need synthetic decline events we haven't modeled — real future
work, not core to proving the cross-merchant idea).

**ML layer:** LightGBM takes the deterministic features + amount and
outputs a single risk probability. This is the only place a prediction
happens in the whole system — everything upstream of it is exact
arithmetic, which is the actual "AI judgment" story: we use ML for the one
thing that's genuinely non-linear and non-deterministic (does this
combination of signals look like an attack), and nothing else.

## 9. Deterministic vs ML — explicit line

If you can compute it exactly with a formula (a count, a time delta, a
set size), it is deterministic and lives in `engine.py`. If it requires
weighing several signals against each other in a way no single threshold
rule captures well, it's the model's job. The model never sees "was this
fraud" as an input to a rule — only the raw counts.

## 10. ML formulation

Binary classification. LightGBM (`gbdt`, binary objective). Training
samples weighted so that misclassifying a legitimate transaction as fraud
costs more during training than missing a low-value fraud-test
transaction (ratio matches the cost assumption in Section 15 — kept as a
single constant so the two never silently disagree, which was the actual
bug in an earlier draft of this project).

## 11. Target/label definition

The label is **synthetic ground truth generated by our own simulator** —
a transaction is labeled fraud if and only if the simulator generated it
as part of an attack burst. This is a proxy for real fraud, not real
fraud. State this explicitly in the pitch: we are proving the *approach*
detects a known-injected pattern, not that we've validated against real
Razorpay fraud data (which we don't have access to).

## 12. Data-generation strategy

A seeded, reproducible simulator (fixed random seed => same dataset every
run, which matters for anyone trying to verify your numbers). Generates:
- baseline organic traffic across ~30 merchants, realistic amount range
- card-testing bursts: shared device/IP, spread across many merchants,
  low-value amounts
- **deliberately overlapping edge cases** — some organic low-value
  transactions (UPI top-ups, small recharges) and some bot attempts at
  higher amounts — so the classes aren't trivially separable by amount
  alone. (This directly answers the "why not just threshold on amount"
  question a judge will ask.)

## 13. Attack simulation strategy

Time-phased stream for the demo: N seconds of normal traffic, then an
attack injection ramps up over M seconds, visible live on the dashboard
as velocity and risk score climb, culminating in incident detection and a
visible shift in decisions from ALLOW to BLOCK/STEP-UP.

## 14. Risk policy

Three tiers — ALLOW / STEP-UP / BLOCK — with thresholds chosen by
sweeping the validation set and picking the point that minimizes:

```
Total Cost = FP x Cost_FP + FN x Cost_FN
```

`Cost_FP` and `Cost_FN` are **explicitly labeled as prototype assumptions**
in all output (metrics report, dashboard, pitch), never presented as
Razorpay's real cost figures. STEP-UP is used as a middle tier for scores
near the boundary rather than treating every flagged transaction with the
same severity.

## 15. Evaluation methodology

Held-out validation set (separate random seed from training, not just a
split of the same generation run — reduces the chance the model
memorizes simulator quirks). Report: precision, recall, F1, PR-AUC,
ROC-AUC, false-positive rate, false-negative rate, full confusion matrix,
and a threshold-sensitivity table (metrics at 5-6 different thresholds,
not just the chosen one) so a judge can see the trade-off, not just the
winning number.

## 16. Benchmark methodology

Measured, not claimed:
- feature-extraction + scoring latency per request, p50/p95/p99, over a
  batch of >=500 requests
- a simple concurrency test (async batches of increasing concurrent
  requests) to see where latency starts to degrade
- all results reported as **"measured locally under our benchmark
  workload"** — never "Razorpay production latency," since we have no
  access to their infrastructure or real traffic shape

## 17. AI Investigator architecture (stretch — Day 5 only)

```
BLOCK-tier incident
  -> structured evidence object assembled from Redis/logs
     (the actual feature values + recent related events — nothing else)
  -> LLM investigator, instructed to reference ONLY the provided evidence
  -> output: incident summary, cited evidence, hypothesis, recommended
     action (never an autonomous decision)
```

## 18. Agent tools

Read-only retrieval functions only: `get_device_history(device_id)`,
`get_ip_history(ip)`, `get_merchant_spread(device_id)` — all backed by
the same Redis data the deterministic engine already uses. No free-form
tool use, no write access, no ability to change a decision.

## 19. AI guardrails

- Investigator prompt explicitly forbids citing anything not present in
  the structured evidence object.
- Output is always labeled "recommendation," never "decision" — the
  policy layer's decision is already final by the time the investigator
  runs.
- If the LLM call fails or no API key is configured, a templated note is
  used instead — the safety-critical path never depends on the LLM being
  available.
- Investigator only runs on actual incidents (crossing the trigger
  count), not on every transaction — keeps it off the latency-critical
  path entirely.

## 20. Failure experiments (only these 3 — run for real, documented as they happen)

1. **Naive per-request recomputation vs Redis sliding window.** Implement
   a naive version that recomputes counts by scanning an in-memory list
   per request; measure latency against the Redis ZSET pipeline version.
2. **Accuracy-optimized threshold (0.5 default) vs cost-aware threshold.**
   Show the confusion matrix and net cost at both, side by side — this
   demonstrates *why* the cost-aware approach matters, with real numbers.
3. **Latency under increasing concurrent load.** Simple async load test;
   document where latency starts to degrade and what the likely
   bottleneck is (probably the single Redis connection pool at prototype
   scale — that's a fine, honest answer).

Each documented as: Problem -> Initial approach -> Observed behaviour ->
Root cause -> Fix -> New result, in `docs/failure-recovery.md`, written
as they actually happen — not reconstructed afterward.

## 21. Repository structure

```
razorpay-sentinel/
├── app/
│   ├── main.py
│   ├── engine.py          (renamed from redis_cache.py for clarity)
│   ├── model.py           (renamed from model_engine.py)
│   ├── policy.py          (extracted from model.py — decision logic separate from ML)
│   ├── simulator.py       (renamed from tracker_simulator.py)
│   ├── schemas.py         (pydantic models, extracted from main.py)
│   └── investigator/      (stretch, Day 5)
├── ml/
│   ├── train.py
│   └── evaluate.py        (produces the metrics report — skip a notebook, it's redundant with this)
├── tests/
│   ├── test_engine.py
│   └── test_policy.py
├── dashboard.py
├── requirements.txt
├── README.md
└── docs/
    ├── architecture.md    (this file)
    ├── decisions.md
    └── failure-recovery.md
```

## 22. Implementation plan (confirm real day count before locking this in)

- **Day 1:** finalize this spec, transaction schema, simulator with
  overlapping edge cases (Section 12)
- **Day 2:** feature engine + Redis + unit tests + naive-vs-Redis
  benchmark (Failure experiment 1)
- **Day 3:** model training, threshold sweep, full evaluation report,
  accuracy-vs-cost-aware comparison (Failure experiment 2)
- **Day 4:** policy layer, API, dashboard, concurrency load test
  (Failure experiment 3)
- **Day 5:** AI investigator if MVP is solid, otherwise polish + docs +
  demo recording + buffer

## 23. MVP vs optional

**MVP (must ship):** deterministic feature engine, LightGBM classifier
with cost-aware threshold, policy layer, dashboard with live attack
simulation, real latency benchmarks, 3 documented failure experiments.

**Optional/stretch:** AI Investigator, any relationship features beyond
the basic set-cardinality counts already in Section 8, load-test
visualization on the dashboard itself (vs. just a printed report).

## 24. Demo scenario (5-minute video)

1. Dashboard shows calm, normal traffic (~30s)
2. Click "start card-testing simulation" — velocity and risk score
   visibly climb
3. Incident fires, decisions shift from ALLOW to BLOCK/STEP-UP live
4. Cut to metrics panel: precision/recall/cost table, latency p50/p95/p99
5. If built: one AI investigator incident note, read aloud
6. Close with the one real failure story (pick the most visually
   demonstrable of the 3 — likely the naive-vs-Redis latency comparison,
   it's an easy before/after number to show)

## 25. Risks / limitations (state these upfront in the pitch, don't wait to be asked)

- All data is synthetic; labels are simulator-defined, not real fraud
  ground truth
- Cost figures (Cost_FP, Cost_FN) are illustrative prototype assumptions,
  not Razorpay's actual financial figures
- Single-node Redis, no high-availability story — fine for a prototype,
  stated as a known limitation rather than hidden
- The AI Investigator (if built) adds latency and API cost, so it's
  deliberately kept off the authorization-critical path

## 26. What NOT to build

No Kafka, no Kubernetes, no microservice sprawl, no vector database, no
graph database. No merchant-specific baseline deviation (cut, Section 8).
No autonomous auto-ban of a card or device — every BLOCK is a reversible,
single-transaction decline, never a permanent action. No claim of
"production Razorpay latency" anywhere. No free-text LLM fraud
decisioning — the policy layer's decision is always final before the
investigator ever runs.

---

## Cuts from original scope (explicit, per your instruction to be critical)

- Merchant-specific baseline deviation — cut, not deferred well enough
  to justify the infra cost in this timeframe
- Burstiness/variance features — cut, marginal value over plain velocity
  counts
- 3 of the original 6 failure experiments — cut (agent-workflow
  optimization comparisons, merchant-baseline comparisons) — nothing
  honest to compare yet at this scope
- Evaluation notebook — replaced with `ml/evaluate.py` producing a
  metrics report directly; a notebook is a nice-to-have, not a
  time-efficient one here
- AI Investigator demoted from core to stretch — the track's explicit
  ask is measured precision/recall on a held-out test set, which is the
  detector, not the investigator
