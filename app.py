import streamlit as st
import random, requests
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="IQC Westgard Agent", page_icon="🧪")

# ---------- Session state ----------
if "runs" not in st.session_state:
    st.session_state.runs = []
if "run_num" not in st.session_state:
    st.session_state.run_num = 0

# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ Control Settings")
    MEAN = st.number_input("Target Mean (mg/dL)", value=100.0, step=1.0)
    SD   = st.number_input("SD", value=5.0, step=0.1, min_value=0.1)
    MODE = st.selectbox("Simulation", ["Normal", "Random Error", "Systematic Shift", "Drift"])
    INTERVAL = st.slider("Feed interval (s)", 1, 5, 2)

    st.divider()
    st.header("📨 Telegram")
    try:
        _tok  = st.secrets["TELEGRAM_TOKEN"]
        _chat = st.secrets["TELEGRAM_CHAT_ID"]
    except Exception:
        _tok = _chat = ""
    TOKEN = st.text_input("Bot Token", value=_tok, type="password")
    CHAT  = st.text_input("Chat ID",   value=_chat)
    if st.button("Send test message"):
        ok = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                           json={"chat_id": CHAT, "text": "✅ Test"}, timeout=8).ok if (TOKEN and CHAT) else False
        st.success("Sent ✓") if ok else st.error("Failed ✗")

    st.divider()
    playing = st.toggle("▶ Live feed", value=True)
    if st.button("🔄 Reset", use_container_width=True):
        st.session_state.runs = []
        st.session_state.run_num = 0
        st.rerun()

# ---------- Helpers ----------
def tg(msg):
    if not (TOKEN and CHAT): return False
    try:
        return requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                             json={"chat_id": CHAT, "text": msg, "parse_mode": "HTML"},
                             timeout=8).ok
    except Exception:
        return False

def gen(m, sd, n):
    if MODE == "Normal":           return random.gauss(m, sd)
    if MODE == "Random Error":     return random.gauss(m + (3.5*sd if random.random() < 0.2 else 0)*random.choice([-1,1]), sd)
    if MODE == "Systematic Shift": return random.gauss(m + (2.5*sd if n >= 8 else 0), sd)
    if MODE == "Drift":            return random.gauss(m + min(n, 15)*0.3*sd, sd)
    return random.gauss(m, sd)

def evaluate(vals, cur, m, sd):
    v = vals + [cur]; n = len(v); rules = []
    if abs(cur - m) > 2*sd: rules.append("1-2s")
    if abs(cur - m) > 3*sd: rules.append("1-3s")
    if n >= 2:
        if all(x > m+2*sd for x in v[-2:]) or all(x < m-2*sd for x in v[-2:]): rules.append("2-2s")
        if abs(v[-1] - v[-2]) > 4*sd: rules.append("R-4s")
    if n >= 4 and (all(x > m+1*sd for x in v[-4:]) or all(x < m-1*sd for x in v[-4:])): rules.append("4-1s")
    if n >= 10 and (all(x > m for x in v[-10:]) or all(x < m for x in v[-10:])): rules.append("10x")

    REJ = {"1-3s","2-2s","R-4s","4-1s","10x"}
    if any(r in REJ for r in rules):
        status, etype = "REJECT", ("Random Error" if any(r in {"1-3s","R-4s"} for r in rules) else "Systematic Error")
    elif "1-2s" in rules:
        status, etype = "WARNING", "Warning"
    else:
        status, etype = "OK", "—"
    return rules, status, etype

SUG = {
    "1-3s": "Random error — check bubbles, clots, pipetting; repeat control",
    "R-4s": "Random error — in-run drift; repeat control",
    "2-2s": "Systematic error — recalibrate; check reagent lot change",
    "4-1s": "Systematic error — verify calibration and reagent stability",
    "10x":  "Systematic shift — investigate calibration and reagent lot",
    "1-2s": "Warning only — review trend, continue with caution",
}

# ---------- Header ----------
st.title("🧪 IQC Westgard Real-Time Agent — Glucose")
st.caption("Auto-analyzer → Westgard rules → error type → suggestion → Telegram")

# ---------- Live feed ----------
@st.fragment(run_every=INTERVAL)
def live():
    if playing:
        vals = [r["value"] for r in st.session_state.runs]
        val = gen(MEAN, SD, len(vals))
        rules, status, etype = evaluate(vals, val, MEAN, SD)
        st.session_state.run_num += 1
        st.session_state.runs.append({
            "run": st.session_state.run_num,
            "time": datetime.now().strftime("%H:%M:%S"),
            "value": round(val, 2),
            "rules": rules,
            "status": status,
            "etype": etype,
        })
        if status == "REJECT":
            sug = " | ".join(SUG.get(r, "") for r in rules if r in SUG)
            tg(f"🚨 <b>IQC REJECT</b>\nRun #{st.session_state.run_num}\n"
               f"Value: <b>{val:.2f}</b> mg/dL\nRules: {', '.join(rules)}\n"
               f"Error: <b>{etype}</b>\n💡 {sug}\nTime: {datetime.now().strftime('%H:%M:%S')}")

    runs = st.session_state.runs
    if not runs:
        st.info("⏳ Starting feed... toggle **Live feed** ON in the sidebar if paused.")
        return

    latest = runs[-1]
    warns   = [r for r in runs if r["status"] == "WARNING"]
    rejects = [r for r in runs if r["status"] == "REJECT"]

    # Metrics strip
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Latest Run", f"#{latest['run']}")
    c2.metric("Latest Value", f"{latest['value']:.2f}")
    c3.metric("Total Runs", len(runs))
    c4.metric("⚠️ Warnings", len(warns))
    c5.metric("🚨 Rejections", len(rejects))

    # Status banner
    if latest["status"] == "REJECT":
        st.error(f"🚨 **Run #{latest['run']} REJECTED** — {latest['value']:.2f} mg/dL — "
                 f"Rules: **{', '.join(latest['rules'])}** — {latest['etype']}")
        for r in latest["rules"]:
            if r in SUG: st.info(f"💡 {SUG[r]}")
    elif latest["status"] == "WARNING":
        st.warning(f"⚠️ **Run #{latest['run']} Warning** — {latest['value']:.2f} mg/dL — Rule 1-2s")
        st.info(f"💡 {SUG['1-2s']}")
    else:
        st.success(f"✅ Run #{latest['run']} OK — {latest['value']:.2f} mg/dL")

    # Levey-Jennings chart with run numbers
    x = [r["run"] for r in runs]
    y = [r["value"] for r in runs]
    colors = ["#d62728" if r["status"]=="REJECT"
              else "#ff7f0e" if r["status"]=="WARNING"
              else "#2ca02c" for r in runs]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines+markers",
        marker=dict(size=10, color=colors, line=dict(width=1, color="white")),
        line=dict(color="#889", width=1.5),
        hovertemplate="Run #%{x}<br>%{y:.2f} mg/dL<extra></extra>",
    ))
    for k, col in [(3,"#d62728"), (2,"#ff7f0e"), (1,"#2ca02c")]:
        fig.add_hline(y=MEAN+k*SD, line_dash="dash", line_color=col,
                      annotation_text=f"+{k}SD", annotation_position="right")
        fig.add_hline(y=MEAN-k*SD, line_dash="dash", line_color=col,
                      annotation_text=f"-{k}SD", annotation_position="right")
    fig.add_hline(y=MEAN, line_color="#1f77b4", line_width=2,
                  annotation_text="Mean", annotation_position="right")
    fig.update_layout(
        title="Levey–Jennings Chart",
        xaxis_title="Control Run #", yaxis_title="mg/dL",
        height=420, margin=dict(l=20, r=80, t=50, b=40),
        showlegend=False, xaxis=dict(dtick=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Separate logs
    t1, t2 = st.tabs([f"⚠️ Warning Log ({len(warns)})", f"🚨 Rejection Log ({len(rejects)})"])
    with t1:
        if not warns:
            st.caption("No warnings yet.")
        for r in warns[::-1][:20]:
            st.warning(f"**Run #{r['run']}** — {r['time']} — {r['value']:.2f} mg/dL — Rule: {', '.join(r['rules'])}")
            st.caption(f"💡 {SUG['1-2s']}")
    with t2:
        if not rejects:
            st.caption("No rejections yet. Try **Random Error** or **Systematic Shift** mode.")
        for r in rejects[::-1][:20]:
            st.error(f"**Run #{r['run']}** — {r['time']} — {r['value']:.2f} mg/dL — "
                     f"Rules: {', '.join(r['rules'])} — **{r['etype']}**")
            sug = " | ".join(SUG.get(x, "") for x in r["rules"] if x in SUG)
            st.caption(f"💡 {sug}")

live()