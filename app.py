from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from netcoop.agents import run_diagnosis
from netcoop.data_generator import SCENARIOS, build_demo_data

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "sample_telemetry.json"
SCENARIO_LABELS = {
    "normal": "Normal operation", "latency_spike": "Latency spike",
    "hardware_failure": "Hardware failure", "link_congestion": "Link congestion",
    "weak_wifi": "Weak Wi-Fi signal", "interface_fault": "Interface fault",
    "dns_dhcp_failure": "DNS / DHCP outage", "interoperability_failure": "Interoperability failure",
    "malformed_input": "Malformed input",
}


def render_topology(topology: dict, highlighted: set[str]) -> str:
    """Self-contained SVG with CSS-animated packet dots; no JS or external data."""
    nodes = topology.get("devices", [])
    links = topology.get("links", [])
    positions = {
        "gateway": (72, 158), "router": (255, 158), "switch": (465, 115),
        "access_point": (660, 70), "service": (465, 258), "device": (660, 250),
    }
    coords = {}
    for i, node in enumerate(nodes):
        kind = str(node.get("type", "device")).lower()
        base = positions.get(kind, (650, 300))
        same = sum(1 for n in nodes[:i] if n.get("type") == kind)
        coords[node.get("id")] = (base[0], base[1] + same * 54)
    lines, packets, labels = [], [], []
    for i, link in enumerate(links):
        a, b = coords.get(link.get("source")), coords.get(link.get("target"))
        if not a or not b: continue
        d = f"M {a[0]+52} {a[1]+21} C {(a[0]+b[0])/2} {a[1]+21}, {(a[0]+b[0])/2} {b[1]+21}, {b[0]} {b[1]+21}"
        high = float(link.get("utilization_pct", 0) or 0) >= 85 or link.get("target") in highlighted
        color = "#ff747e" if high else "#27465c"
        lines.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.5 if high else 1.5}"/>')
        packets.append(f'<circle r="3.5" fill="{"#ff8f95" if high else "#4de2c5"}"><animateMotion dur="{3.2 + i*.65}s" begin="-{i*.7}s" repeatCount="indefinite" path="{d}"/></circle>')
        midx, midy = (a[0]+b[0]+52)/2, (a[1]+b[1]+42)/2 - 9
        labels.append(f'<text x="{midx}" y="{midy}" class="load">{float(link.get("utilization_pct",0) or 0):.0f}%</text>')
    cards = []
    for node in nodes:
        x, y = coords.get(node.get("id"), (0, 0))
        is_hot = node.get("id") in highlighted
        color = "#ff747e" if is_hot else "#4de2c5"
        label = escape(str(node.get("label", node.get("id", "Node")))[:22])
        node_id = escape(str(node.get("id", ""))[:20])
        cards.append(f'<g><rect x="{x}" y="{y}" width="112" height="43" rx="10" fill="#102638" stroke="{color}" stroke-width="{1.7 if is_hot else 1}"/><circle cx="{x+13}" cy="{y+14}" r="3.5" fill="{color}"/><text x="{x+23}" y="{y+17}" class="label">{label}</text><text x="{x+12}" y="{y+33}" class="id">{node_id}</text></g>')
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}} body{{margin:0;background:#091824;font-family:Manrope,Arial,sans-serif;color:#dfeaf2}}
    .frame{{height:370px;border:1px solid #1b3548;border-radius:14px;background:radial-gradient(ellipse at 45% 45%,#102536,#091824 70%);overflow:hidden;position:relative}}
    svg{{width:100%;height:100%}} .label{{font-size:9px;fill:#dce8f1;font-weight:700}} .id{{font-size:7px;fill:#7891a4;font-family:monospace}} .load{{font-size:9px;fill:#8ea6b9;font-family:monospace}}
    .legend{{position:absolute;right:14px;top:13px;font-size:9px;color:#859cae;font-family:monospace;letter-spacing:.06em}} .legend b{{color:#4de2c5;font-weight:400}} .key{{color:#ff858c!important}}
    </style></head><body><div class="frame"><div class="legend"><b>●</b> LIVE FLOW &nbsp; <b class="key">●</b> ELEVATED</div><svg viewBox="0 0 800 340" preserveAspectRatio="xMidYMid meet">{''.join(lines)}{''.join(labels)}{''.join(packets)}{''.join(cards)}</svg></div></body></html>'''


st.set_page_config(page_title="NetCoop AI | Network diagnostics", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --mint:#4de2c5; --blue:#64a8ff; --muted:#8ca3b6; --panel:#0e2030; }
html, body, [class*="css"] { font-family:'Manrope',sans-serif; }
.stApp { background: radial-gradient(ellipse at 70% 0%, #10283a 0%, #07131f 42%); }
.block-container { padding-top:2.1rem; padding-bottom:3rem; max-width:1500px; }
[data-testid="stSidebar"] { background:#091824; border-right:1px solid #1c3447; }
.eyebrow { color:var(--mint); text-transform:uppercase; letter-spacing:.18em; font:500 .72rem 'DM Mono',monospace; }
.hero-title { color:#f0f7fc; font-size:2.25rem; font-weight:800; letter-spacing:-.055em; margin:.2rem 0 0; }
.hero-sub { color:#9cb1c3; font-size:.96rem; margin:.25rem 0 0; }
.pill { display:inline-flex; gap:.45rem; align-items:center; padding:.38rem .72rem; background:#112b3c; border:1px solid #255069; border-radius:999px; color:#a5c9da; font:.7rem 'DM Mono',monospace; }
.dot { width:7px;height:7px;border-radius:50%;background:var(--mint);box-shadow:0 0 12px #4de2c599; }
.metric-card { background:linear-gradient(140deg,#102536,#0b1b29); border:1px solid #1b3548; border-radius:14px; padding:15px 17px 13px; min-height:98px; }
.metric-label { color:#92a8ba;font: .68rem 'DM Mono',monospace; letter-spacing:.1em;text-transform:uppercase; }
.metric-value { color:#f0f7fc;font-size:1.65rem;font-weight:800;letter-spacing:-.06em;margin-top:3px; }
.metric-note { color:#6f879a;font-size:.72rem;margin-top:-2px; }
.section-title { color:#e7f0f7;font-size:1rem;font-weight:750;letter-spacing:-.02em; }
.section-note { color:#8299ac;font-size:.78rem; }
.agent-chip { background:#0f2637;border:1px solid #244154;border-radius:12px;padding:12px;height:100%; }
.agent-chip strong { color:#e7f0f7;font-size:.82rem; }
.agent-chip small { display:block;color:#8da4b7;margin-top:4px;font-size:.7rem; }
.mono { font-family:'DM Mono',monospace; }
div[data-testid="stExpander"] { border:1px solid #1b3548;border-radius:12px;background:#0b1b29; }
div[data-testid="stDataFrame"] { border:1px solid #1b3548;border-radius:12px;overflow:hidden; }
div[data-testid="stDownloadButton"] button { background:#4de2c5;color:#07131f;border:0;font-weight:800; }
div[data-testid="stButton"] button { border-radius:10px; }
.stAlert { border-radius:12px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_demo():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return build_demo_data()


demo = load_demo()
records_by_scenario = {row.get("scenario"): row for row in demo.get("records", [])}

with st.sidebar:
    st.markdown('<div class="eyebrow">NetCoop AI</div>', unsafe_allow_html=True)
    st.markdown("## Incident lab")
    st.caption("Synthetic campus network · operator review")
    scenario = st.selectbox("Demo scenario", SCENARIOS, format_func=lambda value: SCENARIO_LABELS.get(value, value), index=SCENARIOS.index("link_congestion"))
    run_clicked = st.button("▶  Run agent diagnosis", type="primary", use_container_width=True)
    st.divider()
    st.markdown("**Bring your own telemetry**")
    uploaded = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], help="JSON accepts a record or {records, topology}; CSV accepts one device per row.")
    st.caption("This prototype makes recommendations only. It does not connect to campus infrastructure or perform remediation.")

if "last_scenario" not in st.session_state:
    st.session_state.last_scenario = scenario
    st.session_state.run_clicked = True
if run_clicked or scenario != st.session_state.last_scenario or uploaded is not None:
    st.session_state.run_clicked = True
    st.session_state.last_scenario = scenario

payload = None
input_error = None
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith(".json"):
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
        else:
            frame = pd.read_csv(uploaded)
            payload = [{
                "device_id": str(row.get("device_id", f"CSV_NODE_{i+1}")),
                "device_type": str(row.get("device_type", "device")),
                "site": str(row.get("site", "Uploaded CSV")),
                "status": str(row.get("status", "Unknown")),
                "metrics": {key: row[key] for key in frame.columns if key not in {"timestamp", "device_id", "device_type", "site", "status"} and pd.notna(row[key])},
            } for i, row in frame.iterrows()]
    except Exception as exc:
        input_error = f"Could not read {uploaded.name}: {exc}"
else:
    selected = records_by_scenario.get(scenario)
    payload = {"records": [selected] if selected else [], "topology": demo["topology"]}

if input_error:
    st.error(input_error)
    result = run_diagnosis({})
else:
    result = run_diagnosis(payload)
report = result["report"]

st.markdown('<div class="eyebrow">NETWORK OPERATIONS CENTER <span style="color:#456176">/</span> DIAGNOSTIC WORKSPACE</div>', unsafe_allow_html=True)
head_left, head_right = st.columns([4, 1])
with head_left:
    st.markdown('<div class="hero-title">Network fault diagnosis</div><div class="hero-sub">Independent agents, one evidence trail, a clearer next step.</div>', unsafe_allow_html=True)
with head_right:
    st.markdown('<div style="text-align:right;padding-top:12px"><span class="pill"><span class="dot"></span> SYSTEM READY</span></div>', unsafe_allow_html=True)
st.write("")

records = result["records"]
all_metrics = [r["metrics"] for r in records]
def mean_metric(name):
    values = [m[name] for m in all_metrics if isinstance(m.get(name), (int, float))]
    return sum(values) / len(values) if values else None

def metric_card(label, value, note, suffix=""):
    if value is None:
        value_text = "—"
    elif isinstance(value, (int, float)):
        value_text = f"{value:.1f}{suffix}"
    else:
        value_text = str(value)
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value_text}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)

cols = st.columns(5)
with cols[0]: metric_card("Root cause", "Unknown" if report["status"] != "diagnosed" else report["suspected_root_cause"].replace(" ", "\u00a0"), report["status"].replace("_", " ").title())
with cols[1]: metric_card("Confidence", report["confidence"] * 100, "Rule-based evidence score", "%")
with cols[2]: metric_card("Latency", mean_metric("latency_ms"), "Mean of available devices", " ms")
with cols[3]: metric_card("Packet loss", mean_metric("packet_loss_pct"), "Mean of available devices", "%")
with cols[4]: metric_card("Agent messages", len(result["agent_messages"]), "Structured handoffs")

if result["warnings"]:
    with st.expander(f"Input validation · {len(result['warnings'])} warning(s)", expanded=True):
        for warning in result["warnings"]:
            st.warning(warning)

left, right = st.columns([1.65, 1], gap="large")
with left:
    st.markdown('<div class="section-title">Live network topology</div><div class="section-note">Animated packets follow the monitored paths. Highlight indicates the strongest observed fault signal.</div>', unsafe_allow_html=True)
    topology = result["topology"] or demo["topology"]
    warning_nodes = set(report["affected_devices"])
    metrics_to_highlight = {e["device_id"] for e in report["supporting_evidence"]}
    st.components.v1.html(render_topology(topology, warning_nodes | metrics_to_highlight), height=385, scrolling=False)
    st.markdown('<div class="section-title">Telemetry snapshot</div>', unsafe_allow_html=True)
    table = []
    for row in records:
        table.append({"Device": row["device_id"], "Type": row["device_type"], "Status": row["status"], **row["metrics"]})
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

with right:
    st.markdown('<div class="section-title">Diagnostic report</div><div class="section-note">Evidence-ranked recommendation for operator review</div>', unsafe_allow_html=True)
    if report["status"] == "diagnosed":
        st.success(report["suspected_root_cause"])
    else:
        st.warning("Insufficient evidence for a reliable root-cause claim")
    st.markdown(f"**Incident**  <span class='mono'>{report['incident_id']}</span> &nbsp; · &nbsp; **Confidence** {report['confidence']:.0%}", unsafe_allow_html=True)
    if report["supporting_evidence"]:
        st.markdown("**Supporting evidence**")
        for evidence in report["supporting_evidence"][:5]:
            st.markdown(f"- `{evidence['device_id']}` · **{evidence['metric']}** {evidence['value']} {evidence['unit']} — {evidence['interpretation']}")
    else:
        st.caption("No validated evidence crossed the reporting threshold.")
    st.markdown("**Recommended next steps**")
    for action in report["recommended_actions"]:
        st.markdown(f"- {action}")
    if report["alternative_causes"]:
        with st.expander("Alternative explanations"):
            for alternative in report["alternative_causes"]:
                st.write("• " + alternative)
    if report["limitations"]:
        with st.expander("Limitations and input notes"):
            for limitation in report["limitations"]:
                st.write("• " + limitation)

st.divider()
st.markdown('<div class="section-title">Agent collaboration trace</div><div class="section-note">Three telemetry specialists → evidence correlation → unified report</div>', unsafe_allow_html=True)
agents = [
    ("Performance", "Latency · loss · jitter · link load"),
    ("Infrastructure", "CPU · memory · queues · interfaces"),
    ("Connectivity", "Topology · scope · services"),
    ("Fault correlation", "Evidence families · competing causes"),
    ("Reporting", "Confidence · actions · JSON output"),
]
agent_cols = st.columns(5)
for col, (name, subtitle) in zip(agent_cols, agents):
    with col:
        st.markdown(f'<div class="agent-chip"><strong>◉ &nbsp;{name}</strong><small>{subtitle}</small></div>', unsafe_allow_html=True)
with st.expander("Inspect structured agent messages"):
    for message in result["agent_messages"]:
        st.markdown(f"**{message['source_agent']}** → `{message['target_agent']}` · `{message['status']}`")
        st.json(message, expanded=False)
if result["ranked_candidates"]:
    with st.expander("Correlation scoring"):
        st.caption("Up to 0.30 per independent family plus up to 0.10 for corroboration. Requires score ≥ 0.42 and two evidence families; capped at 0.95.")
        st.dataframe(pd.DataFrame([{"Candidate": c["cause"], "Score": c["score"], "Families": ", ".join(c["families"]), "Signals": len(c["evidence"])} for c in result["ranked_candidates"]]), use_container_width=True, hide_index=True)

st.download_button("Download diagnostic report · JSON", data=json.dumps(report, indent=2), file_name=f"{report['incident_id'].lower()}_report.json", mime="application/json")
st.caption("NetCoop AI prototype · synthetic data · all corrective actions remain recommendations for a human operator.")

