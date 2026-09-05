# Stochastix AI — The Complete Picture

One document. Everything. Read this top to bottom once, then use it as
your map for the rest of the build.

---

## 1. The problem, in one paragraph

An attacker with thousands of stolen card numbers doesn't know which
ones still work. Testing them one at a time on one merchant is loud and
gets caught fast — so instead they spread tiny ₹2-15 test transactions
across dozens of *different* merchants at once. Each merchant sees one
small, harmless-looking payment. Nobody at any single merchant sees the
pattern. But Razorpay — sitting above all those merchants — is the one
place that *can* see it: the same device or card hitting many merchants
in a few seconds. That blind spot, and how to close it without slowing
down real customers, is the whole project.

## 2. Why this isn't a generic project

Most entrants will build: transaction → some model → risk score. That's
a fraud API wrapper, not a risk system. Yours is different because it
answers a sharper, provable question:

> **Does seeing across merchants catch attacks that no single merchant
> could ever see on their own — and does it do that without wrongly
> blocking real customers?**

That's not a claim. As of yesterday, it's a measured result (Section 5).

## 3. The complete architecture

```
                         TRANSACTION ARRIVES
                                 |
                                 v
                    ┌────────────────────────┐
                    │   FastAPI gateway       │   <- the door: receives
                    │   (app/main.py)         │      every payment attempt
                    └───────────┬─────────────┘
                                 |
                                 v
                    ┌────────────────────────┐
                    │   Redis feature engine  │   <- DETERMINISTIC.
                    │   (app/engine.py)       │      Exact counts, no AI:
                    │                         │      - txns/60s per device
                    │                         │      - txns/60s per IP
                    │                         │      - distinct merchants
                    │                         │        per device (60s)
                    │                         │      - distinct cards
                    │                         │        per device
                    └───────────┬─────────────┘
                                 |  (a few numbers, computed in ~1ms)
                                 v
                    ┌────────────────────────┐
                    │   LightGBM model        │   <- PREDICTION. Only
                    │   (app/model.py)        │      place ML happens.
                    │                         │      Outputs one number:
                    │                         │      risk probability
                    └───────────┬─────────────┘
                                 |
                                 v
                    ┌────────────────────────┐
                    │   Policy layer          │   <- turns a probability
                    │   (inside model.py)     │      into a real decision,
                    │                         │      using a COST table,
                    │                         │      not a guessed cutoff
                    └───────────┬─────────────┘
                                 |
                  ┌──────────────┼──────────────┐
                  v              v              v
               ALLOW         STEP-UP          BLOCK
             (let it       (extra verify,   (decline this
              through)      e.g. 3DS)        one attempt —
                                              reversible,
                                              never a ban)
                                 |
                          (if BLOCK repeats)
                                 v
                    ┌────────────────────────┐
                    │  Agentic guardrail      │   <- deterministic,
                    │  (app/agent_guard.py)   │      bounded threshold
                    │                         │      tightening +
                    │                         │      LLM-written incident
                    │                         │      note for a human
                    └────────────────────────┘
```

**The one-sentence AI-judgment summary:** counting is deterministic,
predicting risk is ML, deciding what a risk score is *worth* is a cost
policy, and explaining an incident to a human is the only place an LLM
touches this system — it never decides anything itself.

## 4. What's already built, and PROVEN (not claimed)

This happened yesterday, for real, in this exact repo:

- **Baseline experiment:** a rule any single merchant could write
  (`app/baseline.py`) catches **11.7%** of a coordinated attack.
- **Sentinel:** the same attack, same test data, caught **98.3%**, with
  **zero** false positives added.
- **A real bug was found and fixed:** trained only on one attack pattern
  (shared device + shared IP), Sentinel completely missed a variant
  where the IP rotates (0% recall). Root cause: the model had learned a
  spurious dependency between two correlated features. Fixed by training
  on a mix of attack patterns → recovered to 96.7% recall on the
  rotating-IP variant.
- All of this is written up, with numbers, in `docs/failure-recovery.md`.

**This is not a plan. This already happened. You have real evidence.**

## 5. The unique angle for your pitch (locked in, after reviewing outside ideas)

Position it as: **"Cross-Merchant Abuse Intelligence — card-testing is
the first attack class, the underlying signal (device/merchant/card
relationships) generalizes to other coordinated abuse."** Don't chase a
Graph Neural Network or a fake-bank-page honeypot — both are either too
slow to build safely in your remaining days or actively risky to pitch
to a security-conscious judge. Your `merchant_diversity_device` feature
*is* the lightweight, shippable version of the "graph" idea — a device's
degree in a device↔merchant graph, computed with a Redis set, not a GNN.

## 6. Where you are right now on the calendar

Deadline: **Sept 4**. Today: Day 3 of 6.

- [x] Day 1: schema, simulator with realistic overlap + 3 attack versions, baseline rule
- [x] Day 2: feature engine wired up, headline experiment run, one real bug found and fixed
- [ ] Day 3 (today): policy layer cleanup, full evaluation report with cost table
- [ ] Day 4: dashboard with live attack-simulation demo
- [ ] Day 5: AI Investigator (only if Day 1-4 solid), else polish
- [ ] Day 6: failure-recovery writeup finalize, record demo video, buffer

## 7. Run it yourself, right now — this is the part that will make it feel real

Everything below is on YOUR machine, not mine. Takes about 10 minutes.

```bash
# 1. Install Redis (if you don't have it) and start it
#    Windows: use WSL, or install Redis via a Windows port / Docker
#    Mac: brew install redis && brew services start redis
#    Linux: sudo apt install redis-server && redis-server --daemonize yes

# 2. Get the code (from the zip I gave you earlier, or ask me to
#    re-export the current state of the repo)

# 3. Install Python dependencies
pip install -r requirements.txt --break-system-packages

# 4. Run the standalone pipeline test — this trains the model and
#    prints real precision/recall/latency numbers, no server needed
python test_pipeline.py

# 5. Run the headline experiment yourself
python experiments/day2_baseline_vs_sentinel.py

# 6. Run the attack-evolution stress test yourself
python experiments/day2_attack_evolution_stress_test.py
```

When you run step 6 and watch V2 recall collapse to 0% and then (after
we apply the fix in the code) recover to 96.7%, on your own screen, with
your own hands typing the command — that's the moment this stops being
"something Claude built" and becomes something you understand and own.
That's genuinely more valuable to you right now than any new feature.

## 8. Your 5-minute pitch skeleton (fill in as we build)

1. **0:00–0:40** — the problem: show a fragmented attack, ₹5/₹3/₹7 across merchants
2. **0:40–1:20** — the insight: merchant sees one event, platform sees the network
3. **1:20–2:30** — live demo: trigger attack, watch risk score climb, decision shift
4. **2:30–3:30** — the honest science: baseline 11.7% vs Sentinel 98.3%, cost table
5. **3:30–4:20** — AI judgment: why Redis, why LightGBM, why the LLM never decides
6. **4:20–5:00** — the real failure story: V2 blindness, root cause, the fix, the new number
