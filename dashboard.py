import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import math
from app.model import FALSE_POSITIVE_COST, FALSE_NEGATIVE_COST
from app.policy import STEP_UP_MULTIPLIER

# NOTE: internal API base, routes, and module names are unchanged on purpose
# (compatibility). Only user-facing branding/styling below has moved to Stochastix AI.
API_BASE = "http://127.0.0.1:8000"

PRODUCT_NAME = "Stochastix AI"
RISK_COLORS = {"ALLOW": "#3E8E5A", "3DS_STEP_UP": "#D9D324", "BLOCK": "#B52E2E"}

st.set_page_config(layout="wide", page_title=f"{PRODUCT_NAME} — Risk Intelligence")

# ---------------------------------------------------------------------------
# FORCED COFFEE THEME — deliberately does NOT rely on .streamlit/config.toml.
# Targets Streamlit's stable data-testid hooks with !important so it applies
# regardless of any config/theme precedence issue in the environment.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] { background: #F5EAD9 !important; }
    [data-testid="stHeader"] { background: rgba(0,0,0,0) !important; }
    section[data-testid="stSidebar"] {
        background: #3B2A1F !important;
        color: #F5EAD9 !important;
    }
    section[data-testid="stSidebar"] * { color: #F5EAD9 !important; }
    h1, h2, h3 { color: #3B2A1F !important; }
    p, li, span, label { color: #4A3826; }
    .stButton>button {
        background: #C97C3E !important; color: #FFF8F0 !important;
        border: none !important; border-radius: 10px !important; font-weight: 600 !important;
    }
    .stButton>button:hover { background: #B5652A !important; }
    [data-testid="stMetric"] {
        background: #FFF8F0; border: 1px solid #E6D2B5; border-radius: 14px;
        padding: 0.8rem 1rem;
    }
    [data-testid="stExpander"] { border: 1px solid #E6D2B5 !important; border-radius: 12px !important; }
    .stx-badge-row {display:flex; gap:0.6rem; flex-wrap:wrap; margin-bottom:0.5rem;}
    .stx-badge {padding:0.35rem 0.8rem; border-radius:999px; font-size:0.85rem;
                background:#EFDFC4; border:1px solid #D9BE93; color:#5C4A36;}
    .stx-badge.done {background:#DCEFDE; border-color:#A8D2AE; color:#1F6D3F; font-weight:600;}
    .stx-pipeline {display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap;
                   background:#FFF8F0; border:1px solid #E6D2B5; border-radius:14px;
                   padding:1rem 1.2rem; margin-bottom:0.8rem;}
    .stx-step {background:#FFFFFF; border:1px solid #E6D2B5; border-radius:10px;
               padding:0.6rem 0.9rem; font-size:0.9rem; color:#3B2A1F; font-weight:600;
               white-space:nowrap;}
    .stx-arrow {color:#C97C3E; font-size:1.1rem;}
    .stx-callout-honest {background:#FBEBD2; border:1px solid #E8B96B; border-radius:12px;
                          padding:0.9rem 1.1rem; color:#6B4A16;}
    .stx-callout-insight {background:#E6F2E8; border:1px solid #A8D2AE; border-radius:12px;
                           padding:0.9rem 1.1rem; color:#1F6D3F;}
    .stx-stat-card {border-radius:16px; padding:1.1rem 1.2rem; color:#FFF8F0; min-height:110px;}
    .stx-stat-card .label {font-size:0.8rem; opacity:0.9; text-transform:uppercase; letter-spacing:0.03em;}
    .stx-stat-card .value {font-size:1.9rem; font-weight:700; margin:0.2rem 0;}
    .stx-stat-card .sub {font-size:0.78rem; opacity:0.85;}
    </style>
    """,
    unsafe_allow_html=True,
)

if "historical_ledger" not in st.session_state:
    st.session_state.historical_ledger = []
if "story_caption" not in st.session_state:
    st.session_state.story_caption = "Click a scenario below to begin. Nothing has happened yet."
if "acts_seen" not in st.session_state:
    st.session_state.acts_seen = set()

ACT_LABELS = ["1. See the blind spot", "2. Run a scenario", "3. See the reasoning",
              "4. Verify via audit", "5. See the honest limits"]

# ---------- SIDEBAR: gamified progress nav ----------
with st.sidebar:
    st.markdown(f"### ☕ {PRODUCT_NAME}")
    st.caption("AI Risk Manager")
    st.markdown("---")
    st.markdown("**Your progress**")
    for i, label in enumerate(ACT_LABELS, start=1):
        done = i in st.session_state.acts_seen
        st.markdown(f"{'✅' if done else '▫️'} {label}")
    st.markdown("---")
    st.caption("Full evidence: docs/evaluation-report.md · docs/failure-recovery.md")

# ---------- HERO ----------
st.markdown(f"## 🛡️ {PRODUCT_NAME}")
st.caption("AI Risk Manager — cross-merchant card-testing & abuse detection")

try:
    from app.simulator import BuiltInTrafficSimulator
    simulator = BuiltInTrafficSimulator()
except Exception as err:
    st.error(f"Could not load traffic simulator: {err}")
    st.stop()

try:
    metrics_resp = requests.get(f"{API_BASE}/metrics", timeout=2).json()
except Exception:
    st.error(f"API not reachable at {API_BASE}. Start it with: uvicorn app.main:app --reload")
    st.stop()

live_l, live_r = st.columns([3, 2])
with live_l:
    st.markdown(
        f"**● LIVE** &nbsp; | &nbsp; {len(st.session_state.historical_ledger)} txns this session "
        f"&nbsp; | &nbsp; threshold `{metrics_resp['live_threshold']:.4f}` "
        f"&nbsp; | &nbsp; recalibrations `{metrics_resp['recalibration_events']}`"
    )
with live_r:
    reset = st.button("↺ Reset data", use_container_width=False)

if reset:
    st.session_state.historical_ledger = []
    st.session_state.story_caption = "Reset. Nothing has happened yet."
    st.session_state.acts_seen = set()

# ---------- HEADLINE STAT CARDS (coffee-toned, reference-style colored cards) ----------


def stat_card(label, value, sub, color_hex):
    return (
        f'<div class="stx-stat-card" style="background:{color_hex};">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{value}</div>'
        f'<div class="sub">{sub}</div>'
        f'</div>'
    )


sc1, sc2, sc3, sc4 = st.columns(4)
with sc1:
    st.markdown(stat_card(
        "Precision (held-out)", f"{metrics_resp['held_out_metrics']['precision']*100:.1f}%",
        "how many flags were real fraud", "#C97C3E"), unsafe_allow_html=True)
with sc2:
    st.markdown(stat_card(
        "Recall (held-out)", f"{metrics_resp['held_out_metrics']['recall']*100:.1f}%",
        "how much real fraud we caught", "#B5533C"), unsafe_allow_html=True)
with sc3:
    st.markdown(stat_card(
        "Live threshold", f"{metrics_resp['live_threshold']:.4f}",
        "auto-recalibrated, not fixed", "#8C5B4E"), unsafe_allow_html=True)
with sc4:
    st.markdown(stat_card(
        "Recalibration events", f"{metrics_resp['recalibration_events']}",
        "the agent adjusting itself", "#D9A544"), unsafe_allow_html=True)

st.markdown("---")

# ---------- ACT 0a: THE PROBLEM ----------
st.subheader("The problem")
st.write(
    "A single merchant only sees **its own** transactions. An attacker testing stolen cards "
    "spreads attempts across *many* merchants on purpose — so no individual merchant ever sees "
    "enough volume, on their own, to notice. The pattern only becomes visible once you connect "
    "the dots **across** merchants — which is exactly what no single merchant's fraud system can do."
)

# ---------- ACT 0b: HOW IT WORKS ----------
st.subheader("How it works")
st.markdown(
    """
    <div class="stx-pipeline">
        <div class="stx-step">Transaction</div><div class="stx-arrow">→</div>
        <div class="stx-step">Redis evidence<br><span style="font-weight:400;font-size:0.8rem;">card / IP / device velocity</span></div><div class="stx-arrow">→</div>
        <div class="stx-step">ML risk score</div><div class="stx-arrow">→</div>
        <div class="stx-step">Policy decision<br><span style="font-weight:400;font-size:0.8rem;">ALLOW / STEP-UP / BLOCK</span></div><div class="stx-arrow">→</div>
        <div class="stx-step">Audit + explanation</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")

# ---------- GUIDED PROGRESS (on-page badges, mirrors sidebar) ----------
st.subheader("Try it — guided demo")
badges_html = "".join(
    f'<span class="stx-badge {"done" if i in st.session_state.acts_seen else ""}">'
    f'{"✓ " if i in st.session_state.acts_seen else ""}{label}</span>'
    for i, label in enumerate(ACT_LABELS, start=1)
)
st.markdown(f'<div class="stx-badge-row">{badges_html}</div>', unsafe_allow_html=True)

ctrl_legit, ctrl_v1, ctrl_v2, ctrl_v3 = st.columns(4)
with ctrl_legit:
    fire_legit = st.button("Normal traffic (x100)", use_container_width=True)
with ctrl_v1:
    fire_v1 = st.button("Attack V1 — same device+IP", use_container_width=True)
with ctrl_v2:
    fire_v2 = st.button("Attack V2 — rotating IP", use_container_width=True)
with ctrl_v3:
    fire_v3 = st.button("Attack V3 — rotating both", use_container_width=True)


def send_batch(events):
    for event in events:
        try:
            res = requests.post(f"{API_BASE}/api/v1/sentinel/intercept", json=event, timeout=2).json()
            event["decision"] = res["decision"]
            event["risk_score"] = res["risk_score"]
            event["latency_metric"] = float(res["calculated_latency_ms"].replace("ms", ""))
            st.session_state.historical_ledger.append(event)
        except Exception as err:
            st.error(f"Request failed: {err}")
            break


if fire_legit:
    st.session_state.story_caption = (
        "100 ordinary customers are checking out normally, across many different merchants. "
        f"Watch: {PRODUCT_NAME} should leave all of them alone."
    )
    events = [simulator.generate_legitimate_stream() for _ in range(100)]
    for e in events:
        e["attack_label"] = "Normal"
    send_batch(events)

if fire_v1:
    st.session_state.story_caption = (
        "An attacker with a list of stolen cards is now testing them — same device, same "
        "network, spread across many merchants at once. This is the easy case: watch it get caught."
    )
    events = simulator.generate_botnet_burst(scale=40, version=1)
    for e in events:
        e["attack_label"] = "V1 — same device+IP"
    send_batch(events)
    st.session_state.acts_seen.update({2, 3})

if fire_v2:
    st.session_state.story_caption = (
        "The same attacker is now rotating their IP address on every attempt, hoping to look "
        "like separate, unrelated traffic. We don't rely on IP alone — watch it still get caught."
    )
    events = simulator.generate_botnet_burst(scale=40, version=2)
    for e in events:
        e["attack_label"] = "V2 — rotating IP"
    send_batch(events)
    st.session_state.acts_seen.update({2, 3})

if fire_v3:
    st.session_state.story_caption = (
        "Now the attacker rotates BOTH device and IP on every attempt — no shared identity "
        "signal remains. This is our honest, documented limitation: watch most of this leak through."
    )
    events = simulator.generate_botnet_burst(scale=40, version=3)
    for e in events:
        e["attack_label"] = "V3 — rotating both"
    send_batch(events)
    st.session_state.acts_seen.update({2, 3, 5})

st.info(st.session_state.story_caption)

if st.session_state.historical_ledger:
    ledger_df = pd.DataFrame(st.session_state.historical_ledger)
    total_intercepts = len(ledger_df)
    total_blocks = len(ledger_df[ledger_df["decision"] == "BLOCK"])
    total_stepups = len(ledger_df[ledger_df["decision"] == "3DS_STEP_UP"])
    avg_latency = ledger_df["latency_metric"].mean()

    is_fraud_col = ledger_df["is_fraud"] if "is_fraud" in ledger_df.columns else pd.Series([0]*len(ledger_df))
    false_positives = int(((is_fraud_col == 0) & (ledger_df["decision"] != "ALLOW")).sum())
    true_positives = int(((is_fraud_col == 1) & (ledger_df["decision"] != "ALLOW")).sum())
    false_negatives = int(((is_fraud_col == 1) & (ledger_df["decision"] == "ALLOW")).sum())

    st.markdown("---")
    st.subheader("Live metrics")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total intercepted", f"{total_intercepts}")
    m2.metric("Blocks / Step-ups", f"{total_blocks} / {total_stepups}")
    m3.metric("Avg latency", f"{avg_latency:.2f} ms")
    m4.metric("False positives (legit blocked)", false_positives)

    st.subheader("Financial impact (illustrative prototype cost assumptions)")
    fraud_cost_avoided = true_positives * FALSE_NEGATIVE_COST
    false_positive_cost_incurred = false_positives * FALSE_POSITIVE_COST
    missed_fraud_cost = false_negatives * FALSE_NEGATIVE_COST
    f1, f2, f3 = st.columns(3)
    f1.metric("Fraud cost avoided (units)", fraud_cost_avoided)
    f2.metric("False-positive cost incurred (units)", false_positive_cost_incurred)
    f3.metric("Missed-fraud cost (units)", missed_fraud_cost)
    st.caption(
        f"Assumes false positive = {FALSE_POSITIVE_COST} units, false negative = {FALSE_NEGATIVE_COST} units "
        "(stated prototype assumptions, not real production figures — see docs/evaluation-report.md)."
    )

    st.markdown("---")
    st.subheader("Risk trace — every transaction, in order")
    color_map = RISK_COLORS
    colors = ledger_df["decision"].map(color_map)
    fig = go.Figure(go.Scatter(
        x=ledger_df.index, y=ledger_df["risk_score"], mode="markers",
        marker=dict(color=colors, size=10),
        text=ledger_df["decision"], hovertemplate="risk=%{y:.4f}<br>%{text}<extra></extra>",
    ))
    fig.update_layout(
        title="Risk score per transaction (green=allow, orange=step-up, red=block)",
        yaxis_title="Risk score", xaxis_title="Transaction order",
        template="plotly_white", paper_bgcolor="#F5EAD9", plot_bgcolor="#FFF8F0",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Act 3 — Why the last decision happened")
    last = ledger_df.iloc[-1]
    threshold = metrics_resp["live_threshold"]
    stepup_ceiling = threshold * STEP_UP_MULTIPLIER
    if last["decision"] == "ALLOW":
        reason = f"score {last['risk_score']:.3f} stayed under the threshold ({threshold:.3f})."
    elif last["decision"] == "3DS_STEP_UP":
        reason = (
            f"score {last['risk_score']:.3f} crossed the threshold ({threshold:.3f}) but stayed "
            f"under the block ceiling ({stepup_ceiling:.3f}) — ambiguous, so challenge, not decline."
        )
    else:
        reason = (
            f"score {last['risk_score']:.3f} blew past both the threshold ({threshold:.3f}) "
            f"and the step-up ceiling ({stepup_ceiling:.3f})."
        )
    st.markdown(f'<div class="stx-callout-insight"><b>{last["decision"]}</b> on <code>{last["transaction_id"]}</code> — {reason}</div>', unsafe_allow_html=True)

    # Best-effort: pull raw evidence for the last transaction from the audit endpoint.
    # NOTE: assumes the audit record includes the feature names engine.py computes
    # (velocity_60s_card/ip/device, merchant_diversity_device, amount). If your
    # audit schema uses different keys, paste main.py/audit_db.py and I'll fix this.
    try:
        evidence_resp = requests.get(f"{API_BASE}/audit/{last['transaction_id']}", timeout=2)
        if evidence_resp.status_code == 200:
            ev = evidence_resp.json()
            ev1, ev2, ev3, ev4, ev5 = st.columns(5)
            ev1.metric("Amount", ev.get("amount", "—"))
            ev2.metric("Card velocity (60s)", ev.get("velocity_60s_card", "—"))
            ev3.metric("IP velocity (60s)", ev.get("velocity_60s_ip", "—"))
            ev4.metric("Device velocity (60s)", ev.get("velocity_60s_device", "—"))
            ev5.metric("Merchant diversity", ev.get("merchant_diversity_device", "—"))
    except Exception:
        pass

    st.markdown("---")
    st.subheader("Act 1 — What a naive, single-merchant system would have missed")
    st.caption(
        "Baseline = a fraud check that only sees ITS OWN merchant's history. "
        "Recomputed live from the ledger above — not a canned number."
    )
    from app.baseline import MerchantLocalBaseline

    naive_missed = 0
    for device, group in ledger_df.groupby("device_fingerprint"):
        baseline = MerchantLocalBaseline()
        baseline_flagged = any(
            baseline.score_transaction({
                "merchant_id": r["merchant_id"], "device_fingerprint": device, "amount": r["amount"]
            }) == "BLOCK"
            for _, r in group.iterrows()
        )
        sentinel_caught = (group["decision"] != "ALLOW").any()
        if not baseline_flagged and sentinel_caught:
            naive_missed += 1
            st.session_state.acts_seen.add(1)

    st.metric("Devices that looked harmless to EVERY merchant individually — but weren't", naive_missed)
    st.caption(
        "Uses the actual tested MerchantLocalBaseline class (app/baseline.py). "
        "With ~29 merchants and a 40-transaction burst, the baseline can occasionally flag "
        "a device by pure chance (a merchant gets hit 4+ times by luck) — so this number "
        "can legitimately read 0 sometimes. That's honest small-sample behavior, not a bug."
    )
    
    if naive_missed:
        st.markdown(
            f'<div class="stx-callout-insight">{naive_missed} device(s) only became visible as an '
            'attack once you connect the merchants. That\'s the whole thesis, proven on your own data.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.subheader("Scenario comparison — V1 vs V2 vs V3")
    if "attack_label" in ledger_df.columns:
        comp = ledger_df.groupby("attack_label")["decision"].value_counts(normalize=True).unstack(fill_value=0) * 100
        comp = comp.reindex(columns=["ALLOW", "3DS_STEP_UP", "BLOCK"], fill_value=0).round(1)
        st.dataframe(comp.style.format("{:.1f}%"), use_container_width=True)
        if "V3 — rotating both" in comp.index:
            v3_intervention = 100 - comp.loc["V3 — rotating both", "ALLOW"]
            st.markdown(
                f'<div class="stx-callout-honest">⚠️ <b>Honest limitation:</b> V3 (rotating both device '
                f'and IP) is caught at a much lower rate ({v3_intervention:.1f}% intervention) than V1/V2. '
                'No shared identity signal survives full rotation — this is a known coverage boundary, '
                'not a hidden success. Roadmap: behavioral/network-graph signals that don\'t depend on '
                'device or IP continuity.</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.subheader("Cross-merchant view — the actual thesis, visualized")
    st.caption(
        "This is what a single merchant CANNOT see: the same device fanning out across "
        "many merchants. Built from real ledger data above, not illustrative fake data."
    )
    device_counts = ledger_df["device_fingerprint"].value_counts()
    top_device = device_counts.index[0] if len(device_counts) else None
    if top_device and device_counts.iloc[0] > 1:
        device_rows = ledger_df[ledger_df["device_fingerprint"] == top_device]
        merchants_hit = device_rows["merchant_id"].unique().tolist()
        overall_decision = device_rows["decision"].mode().iloc[0] if len(device_rows) else "ALLOW"
        node_color = RISK_COLORS.get(overall_decision, "#8C7B6A")

        n = len(merchants_hit)
        angle_step = 2 * math.pi / max(n, 1)
        xs, ys = [0], [0]
        edge_x, edge_y = [], []
        for i, m in enumerate(merchants_hit):
            mx, my = math.cos(i * angle_step), math.sin(i * angle_step)
            xs.append(mx); ys.append(my)
            edge_x += [0, mx, None]
            edge_y += [0, my, None]

        net_fig = go.Figure()
        net_fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                       line=dict(color=node_color, width=1.5), hoverinfo="none"))
        net_fig.add_trace(go.Scatter(
            x=[0], y=[0], mode="markers+text", marker=dict(size=28, color="#3B2A1F"),
            text=["device"], textposition="bottom center", name="device",
        ))
        net_fig.add_trace(go.Scatter(
            x=xs[1:], y=ys[1:], mode="markers+text", marker=dict(size=18, color=node_color),
            text=merchants_hit, textposition="top center", name="merchants",
        ))
        net_fig.update_layout(
            title=f"One device -> {n} different merchants (overall: {overall_decision})",
            showlegend=False, template="plotly_white",
            paper_bgcolor="#F5EAD9", plot_bgcolor="#FFF8F0",
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        st.plotly_chart(net_fig, use_container_width=True)
    else:
        st.caption("Run an attack scenario (V1/V2/V3) to see a device's real merchant fan-out here.")

    st.markdown("---")
    with st.expander("Advanced: audit lookup & incident log (available, but not the main story)"):
        st.subheader("Act 4 — Proof (verify it yourself)")
        lookup_col1, lookup_col2 = st.columns([3, 1])
        with lookup_col1:
            lookup_id = st.text_input("Transaction ID", value=str(ledger_df.iloc[-1]["transaction_id"]) if len(ledger_df) else "")
        with lookup_col2:
            st.write("")
            st.write("")
            do_lookup = st.button("Look up")
        if do_lookup and lookup_id:
            try:
                audit_resp = requests.get(f"{API_BASE}/audit/{lookup_id}", timeout=2)
                if audit_resp.status_code == 200:
                    st.json(audit_resp.json())
                    st.session_state.acts_seen.add(4)
                else:
                    st.warning(f"Not found (status {audit_resp.status_code})")
            except Exception as err:
                st.error(f"Lookup failed: {err}")

        st.subheader("Agentic guardrail incident log")
        try:
            incidents = requests.get(f"{API_BASE}/incidents", timeout=2).json()
            if incidents:
                for inc in incidents:
                    st.write(inc["note"])
                    st.json(inc["cluster_summary"])
            else:
                st.write("No recalibration events yet — trigger enough BLOCKs (V1/V2 attacks) to see one fire.")
        except Exception as err:
            st.write(f"Could not fetch incident log: {err}")
else:
    st.info("Run a scenario above to start.")

st.markdown("---")
with st.expander("Act 5 — Why this approach (and where it's honest about its limits)", expanded=True):
    st.markdown(
        f"""
**Cross-merchant intelligence** — detects patterns invisible to any single merchant.

**Real-time, cost-aware decisioning** — risk score → policy → ALLOW / STEP-UP / BLOCK,
using a stated cost tradeoff, not a guessed threshold.

**Adversarial self-testing** — V1 → V2 → V3 shows the attack adapting, and shows
where {PRODUCT_NAME}'s own visibility runs out, honestly.

**AI-assisted investigation, not AI-controlled enforcement** — the LLM explains
incidents using real evidence; it never decides a payment outcome.

**Full auditability** — every decision is permanently recorded and independently
queryable, survives a restart, and never blocks on the audit write.

**Known limitation & roadmap** — V3 (full device+IP rotation) is a documented
coverage boundary, not a success claim. Planned next: signals that don't depend
on device/IP continuity (e.g. behavioral or network-graph based detection).

*"{PRODUCT_NAME} doesn't just ask: is this payment risky? It asks: is this payment part
of a coordinated attack?"*

Full evidence: `docs/evaluation-report.md` · `docs/failure-recovery.md`
        """
    )