from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from netcoop.agents import run_diagnosis
from netcoop.data_generator import SCENARIOS, build_demo_data
from netcoop.workflow_store import WorkflowStore

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "sample_telemetry.json"
WORKFLOW_DB = ROOT / "state" / "netcoop_workflows.sqlite3"
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
        color = "#ff623e" if high else "#08bff5"
        lines.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.5 if high else 1.5}"/>')
        packets.append(f'<circle r="3.5" fill="{"#ff9a39" if high else "#08bff5"}"><animateMotion dur="{3.2 + i*.65}s" begin="-{i*.7}s" repeatCount="indefinite" path="{d}"/></circle>')
        midx, midy = (a[0]+b[0]+52)/2, (a[1]+b[1]+42)/2 - 9
        labels.append(f'<text x="{midx}" y="{midy}" class="load">{float(link.get("utilization_pct",0) or 0):.0f}%</text>')
    cards = []
    for node in nodes:
        x, y = coords.get(node.get("id"), (0, 0))
        is_hot = node.get("id") in highlighted
        color = "#ff623e" if is_hot else "#08bff5"
        label = escape(str(node.get("label", node.get("id", "Node")))[:22])
        node_id = escape(str(node.get("id", ""))[:20])
        cards.append(f'<g><rect x="{x}" y="{y}" width="112" height="43" rx="10" fill="#151517" stroke="{color}" stroke-width="{1.7 if is_hot else 1}"/><circle cx="{x+13}" cy="{y+14}" r="3.5" fill="{color}"/><text x="{x+23}" y="{y+17}" class="label">{label}</text><text x="{x+12}" y="{y+33}" class="id">{node_id}</text></g>')
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}} body{{margin:0;background:#080808;font-family:Manrope,Arial,sans-serif;color:#f1f1f1}}
    .frame{{height:370px;border:1px solid #29292c;border-radius:14px;background:radial-gradient(ellipse at 45% 45%,#1b100d,#080808 70%);overflow:hidden;position:relative}}
    svg{{width:100%;height:100%}} .label{{font-size:9px;fill:#eeeeef;font-weight:700}} .id{{font-size:7px;fill:#85858b;font-family:monospace}} .load{{font-size:9px;fill:#aaa;font-family:monospace}}
    .legend{{position:absolute;right:14px;top:13px;font-size:9px;color:#999;font-family:monospace;letter-spacing:.06em}} .legend b{{color:#08bff5;font-weight:400}} .key{{color:#ff623e!important}}
    </style></head><body><div class="frame"><div class="legend"><b>●</b> LIVE FLOW &nbsp; <b class="key">●</b> ELEVATED</div><svg viewBox="0 0 800 340" preserveAspectRatio="xMidYMid meet">{''.join(lines)}{''.join(labels)}{''.join(packets)}{''.join(cards)}</svg></div></body></html>'''


st.set_page_config(page_title="NetCoop AI | Network diagnostics", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700;800;900&family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family:'Manrope',sans-serif; }
.stApp { background:radial-gradient(ellipse at 50% 3%,#241007 0%,#0b0908 29%,#050505 66%);color:#f4f4f4; }
.block-container { padding-top:1rem;padding-bottom:3rem;max-width:1420px; }
[data-testid="stHeader"] { background:#060606; }
[data-testid="stSidebar"] { background:#0a0a0b;border-right:1px solid #242426; }
[data-testid="stSidebar"] h2 { font-family:'Barlow Condensed',sans-serif;letter-spacing:.08em;text-transform:uppercase; }
.brandbar { display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #262323;padding:12px 2px 15px;margin-bottom:28px; }
.brandmark { color:#f5f5f5;font-size:.85rem;font-weight:900;letter-spacing:.21em;text-transform:uppercase; }
.brandmark span { color:#ff8a00; }
.brandmeta { color:#777;font:500 .64rem 'DM Mono',monospace;letter-spacing:.12em; }
.eyebrow { color:#ffc35c;text-transform:uppercase;letter-spacing:.24em;font:500 .68rem 'DM Mono',monospace;text-align:center; }
.hero-title { color:#ff4928;background:linear-gradient(90deg,#ffb12e 0%,#ff5a21 42%,#f12218 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;font:900 clamp(3.3rem,9vw,7.6rem)/.95 'Barlow Condensed',Impact,sans-serif;letter-spacing:.075em;text-align:center;text-shadow:0 0 34px #fa3e192e;margin:.2rem 0 .55rem; }
.hero-sub { color:#eee;font:800 clamp(1.3rem,4vw,2.25rem)/1 'Manrope',sans-serif;letter-spacing:.22em;text-align:center;text-transform:uppercase;margin:.3rem 0 1.1rem; }
.hero-status { width:fit-content;margin:0 auto 1.1rem;padding:.62rem 1.5rem;border:1px solid #782019;border-radius:999px;background:linear-gradient(90deg,#3a090a,#551008,#350908);box-shadow:0 0 30px #ff302444;color:#fff;font:800 .78rem 'Manrope',sans-serif;letter-spacing:.12em;text-align:center; }
.pill { display:inline-flex;gap:.45rem;align-items:center;padding:.38rem .72rem;background:#161719;border:1px solid #36373a;border-radius:999px;color:#c3c3c5;font:.66rem 'DM Mono',monospace; }
.dot { width:7px;height:7px;border-radius:50%;background:#ff3b47;box-shadow:0 0 12px #ff354e; }
.scoreboard { background:linear-gradient(135deg,#101114,#0b0b0c);border:1px solid #252529;border-radius:20px;padding:22px 26px 20px;margin:1.8rem 0 1.3rem;box-shadow:0 18px 55px #0009; }
.scorelabel { color:#bcbcc0;font-size:.78rem;font-weight:750; }
.scorevalue { font:700 2.5rem/.95 'Barlow Condensed',sans-serif;letter-spacing:.02em;margin:.32rem 0;color:#fff; }
.scoremeta { color:#85868a;font: .65rem 'DM Mono',monospace;text-transform:uppercase;letter-spacing:.1em; }
.redtext { color:#ff5d67!important; }.bluetext { color:#08bff5!important; }
.scoreline { height:5px;border-radius:20px;background:linear-gradient(90deg,#ff384a 0 50%,#08baf3 50% 100%);margin:1.1rem 0 .65rem;box-shadow:0 0 15px #ff384a33; }
.source-note { text-align:center;color:#777;font: .64rem 'DM Mono',monospace;letter-spacing:.05em;margin:.7rem 0 1.8rem; }
.metric-card { position:relative;background:linear-gradient(155deg,#151517,#0b0b0c);border:1px solid #28282b;border-radius:13px;padding:15px 16px 13px;min-height:105px;overflow:hidden; }
.metric-card:before { content:'';position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(90deg,#ff4738,#ff9e24); }
.metric-label { color:#939399;font: .64rem 'DM Mono',monospace;letter-spacing:.13em;text-transform:uppercase; }
.metric-value { color:#f9f9fa;font:700 1.55rem/1.12 'Barlow Condensed',sans-serif;letter-spacing:.015em;margin-top:6px;overflow-wrap:anywhere; }
.metric-note { color:#77777c;font-size:.66rem;margin-top:3px; }
.section-title { color:#06bafa;font:800 1.55rem 'Barlow Condensed',sans-serif;letter-spacing:.1em;text-transform:uppercase;text-shadow:0 0 20px #00a7f555; }
.section-note { color:#85858b;font-size:.73rem; }
.agent-chip { background:linear-gradient(145deg,#171719,#0c0c0d);border:1px solid #2a2a2d;border-radius:11px;padding:14px 12px;height:100%;box-shadow:inset 0 1px #ffffff08; }
.agent-chip strong { color:#f5f5f6;font-size:.76rem; }
.agent-chip small { display:block;color:#89898e;margin-top:5px;font-size:.65rem; }
.mono { font-family:'DM Mono',monospace; }
div[data-testid="stExpander"] { border:1px solid #29292c;border-radius:11px;background:#101012; }
div[data-testid="stDataFrame"] { border:1px solid #29292c;border-radius:11px;overflow:hidden; }
div[data-testid="stDownloadButton"] button { background:linear-gradient(90deg,#ff8a00,#ff4331);color:#0a0807;border:0;font-weight:900;letter-spacing:.04em; }
div[data-testid="stButton"] button { border-radius:10px; }
.stAlert { border-radius:11px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_demo():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return build_demo_data()


@st.cache_data(show_spinner=False)
def cached_diagnosis(payload):
    return run_diagnosis(payload)


@st.cache_resource(show_spinner=False)
def get_workflow_store():
    return WorkflowStore(WORKFLOW_DB)


def resume_checkpoint_callback():
    checkpoint_id = st.session_state.get("resume_choice")
    if not checkpoint_id:
        return
    checkpoint = get_workflow_store().load_checkpoint(checkpoint_id)
    if checkpoint:
        get_workflow_store().mark_resumed(checkpoint_id)
        checkpoint["phase"] = "resumed"
        st.session_state["active_checkpoint"] = checkpoint
        st.session_state["scenario"] = checkpoint["scenario"]


def clear_active_checkpoint():
    st.session_state.pop("active_checkpoint", None)


demo = load_demo()
records_by_scenario = {row.get("scenario"): row for row in demo.get("records", [])}
workflow_store = get_workflow_store()
saved_checkpoints = workflow_store.list_checkpoints()

with st.sidebar:
    st.markdown('<div class="eyebrow" style="text-align:left">NETCOOP / INCIDENT LAB</div>', unsafe_allow_html=True)
    st.markdown("## Scenario controls")
    st.caption("Repeatable synthetic campus telemetry")
    if "scenario" not in st.session_state:
        st.session_state["scenario"] = "link_congestion"
    scenario = st.selectbox("Demo scenario", SCENARIOS, format_func=lambda value: SCENARIO_LABELS.get(value, value), key="scenario", on_change=clear_active_checkpoint)
    run_clicked = st.button("▶  Run agent diagnosis", type="primary", use_container_width=True)
    st.divider()
    st.markdown("**Bring your own telemetry**")
    uploaded = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], help="JSON accepts a record or {records, topology}; CSV accepts one device per row.")
    st.markdown("---")
    st.markdown("**Dataset source**")
    st.caption("`data/sample_telemetry.json` · seed `20261031` · Colab-derived synthetic readings")
    st.caption("Switching scenarios selects a fixed fixture record; agents recompute findings from those measurements. This is not live campus telemetry.")
    st.markdown("**Pause / resume**")
    checkpoint_options = [""] + [item["checkpoint_id"] for item in saved_checkpoints]
    st.selectbox("Saved checkpoints", checkpoint_options, key="resume_choice", format_func=lambda key: "Choose saved run" if not key else next((f"{item['checkpoint_id']} · {item['scenario']} · {item['phase']}" for item in saved_checkpoints if item["checkpoint_id"] == key), key))
    st.button("Resume selected checkpoint", on_click=resume_checkpoint_callback, use_container_width=True, disabled=not bool(saved_checkpoints))
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

active_checkpoint = st.session_state.get("active_checkpoint")
if active_checkpoint and uploaded is None and not input_error:
    payload = active_checkpoint["payload"]
    result = active_checkpoint["result"]
elif input_error:
    st.error(input_error)
    result = run_diagnosis({})
else:
    result = cached_diagnosis(payload)
report = result["report"]
st.session_state["current_payload"] = payload
st.session_state["current_result"] = result
st.session_state["current_scenario"] = scenario

scenario_record = records_by_scenario.get(scenario, {})
observed_devices = ", ".join(r["device_id"] for r in result["records"]) or "Awaiting telemetry"
scenario_heading = "UPLOADED TELEMETRY" if uploaded is not None else SCENARIO_LABELS.get(scenario, scenario).upper()
scenario_device = "UPLOADED DATA" if uploaded is not None else str(scenario_record.get("device_id", "SAMPLE RECORD"))
diagnosed = report["status"] == "diagnosed"
status_label = "PROBABLE CAUSE IDENTIFIED" if diagnosed else "MORE EVIDENCE NEEDED"
cause_label = report["suspected_root_cause"] if diagnosed else "No reliable root cause yet"
confidence_label = f"{report['confidence']:.0%}" if diagnosed else "—"
confidence_note = "Evidence score" if diagnosed else "Insufficient validated signals"
source_label = "Uploaded telemetry" if uploaded is not None else "Synthetic demo fixture"
visible_evidence = [item for item in report["supporting_evidence"] if item["metric"] != "topology_scope"][:3]
evidence_html = "".join(
    f'<div class="diag-signal"><span>{escape(str(item["metric"]).replace("_", " "))}</span><b>{escape(str(item["value"]))} {escape(str(item["unit"]))}</b><small>{escape(str(item["device_id"]))}</small></div>'
    for item in visible_evidence
) or '<div class="diag-empty">No measurements passed the evidence threshold. Collect another time-aligned sample before assigning a cause.</div>'
next_step = report["recommended_actions"][0] if report["recommended_actions"] else "Collect more time-aligned telemetry."
st.markdown(f'''<style>
.diagnosis-panel{{background:linear-gradient(135deg,#141416,#0b0b0c);border:1px solid #303034;border-radius:18px;padding:24px 26px 20px;margin:1rem 0 1.35rem;box-shadow:0 18px 50px #0008}}
.diag-top{{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #2b2b2e;padding-bottom:14px}}
.diag-kicker{{color:#99999f;font:500 .66rem 'DM Mono',monospace;letter-spacing:.13em;text-transform:uppercase}}
.diag-status{{padding:6px 10px;border-radius:999px;background:{'#21100d' if diagnosed else '#211c0d'};border:1px solid {'#75382a' if diagnosed else '#6c5525'};color:{'#ff8a65' if diagnosed else '#ffd477'};font:700 .64rem 'DM Mono',monospace;letter-spacing:.07em}}
.diag-main{{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:20px;align-items:center;padding:20px 0 15px}}
.diag-label{{color:#ff9a67;font:500 .66rem 'DM Mono',monospace;letter-spacing:.16em;text-transform:uppercase}}
.diag-cause{{color:#f5f5f6;font:800 clamp(1.55rem,3.4vw,2.6rem)/1.08 'Barlow Condensed',Impact,sans-serif;letter-spacing:.025em;margin:6px 0 0;overflow-wrap:anywhere}}
.diag-confidence{{text-align:right;border-left:1px solid #303034;padding-left:18px}}
.diag-confidence b{{display:block;color:#08bff5;font:800 2rem/1 'Barlow Condensed',sans-serif}}
.diag-confidence small{{display:block;color:#8b8b91;font: .62rem 'DM Mono',monospace;margin-top:5px;text-transform:uppercase;letter-spacing:.07em}}
.diag-evidence{{display:flex;gap:9px;flex-wrap:wrap;margin:5px 0 16px}}
.diag-signal{{min-width:125px;flex:1;background:#101013;border:1px solid #29292d;border-radius:10px;padding:9px 11px}}
.diag-signal span,.diag-signal small{{display:block;color:#88888e;font: .61rem 'DM Mono',monospace;text-transform:uppercase;letter-spacing:.06em}}
.diag-signal b{{display:block;color:#ededf0;font-size:.9rem;margin:4px 0}}
.diag-empty{{color:#aaa;font-size:.77rem;padding:8px 0}}
.diag-bottom{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;border-top:1px solid #2b2b2e;padding-top:13px;color:#999;font-size:.72rem}}
.diag-next{{color:#e2e2e5;max-width:68%}}
@media(max-width:650px){{.diagnosis-panel{{padding:17px}}.diag-main{{grid-template-columns:1fr;gap:12px}}.diag-confidence{{border-left:0;border-top:1px solid #303034;padding:12px 0 0;text-align:left;display:flex;align-items:baseline;gap:8px}}.diag-confidence b{{font-size:1.5rem}}.diag-bottom{{display:block}}.diag-next{{max-width:100%;margin-top:5px}}}}
</style>
<div class="diagnosis-panel">
  <div class="diag-top"><div class="diag-kicker">NETCOOP AI &nbsp; / &nbsp; INCIDENT BRIEF</div><div class="diag-status">● &nbsp; {status_label}</div></div>
  <div class="diag-main"><div><div class="diag-label">{('LIKELY ROOT CAUSE' if diagnosed else 'DIAGNOSIS')}</div><div class="diag-cause">{escape(str(cause_label))}</div></div><div class="diag-confidence"><b>{confidence_label}</b><small>{confidence_note}</small></div></div>
  <div class="diag-evidence">{evidence_html}</div>
  <div class="diag-bottom"><div><span class="diag-kicker">NEXT STEP</span><div class="diag-next">{escape(str(next_step))}</div></div><div style="text-align:right"><span class="diag-kicker">SCENARIO</span><div>{escape(scenario_heading)} · {escape(scenario_device)}</div><span class="diag-kicker">AFFECTED</span><div>{escape(observed_devices)}</div><span class="diag-kicker">SOURCE</span><div>{source_label}</div></div></div>
</div>''', unsafe_allow_html=True)
with st.expander("What is this scenario using?", expanded=False):
    st.caption("These are generated demo readings stored in data/sample_telemetry.json. Their metric values are repeatable for seed 20261031. The selected record is passed through the agents and correlator when selected. The agent rules and action wording are deterministic; no LLM or live network feed is connected.")
    st.download_button("Download the full synthetic dataset", data=json.dumps(demo, indent=2), file_name="netcoop_synthetic_telemetry.json", mime="application/json")
    if uploaded is None and scenario_record:
        st.markdown("**Selected fixture record**")
        st.json(scenario_record, expanded=True)

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
st.caption("NetCoop AI prototype · synthetic data · remediation controls only record a simulation; they never contact network devices.")

with st.expander("Human review · pause/resume · remediation simulation", expanded=False):
    st.markdown("**Human-in-the-loop review**")
    decision = st.radio("Operator decision", ["Approve recommendation for manual follow-up", "Request more telemetry", "Reject this diagnosis"], key="operator_decision")
    review_note = st.text_area("Review note", key="operator_note", placeholder="Add context for the next operator")
    if st.button("Save human review", key="save_review"):
        review_id = workflow_store.save_review(report["incident_id"], decision, review_note)
        st.session_state["review_notice"] = review_id
    if st.session_state.get("review_notice"):
        st.success(f"Review saved locally: {st.session_state['review_notice']}")

    st.markdown("**Remediation preview (simulation only)**")
    proposed_action = st.selectbox("Proposed action", report["recommended_actions"], key="simulated_action")
    if st.button("Simulate proposed action", key="simulate_action"):
        simulation_id = workflow_store.save_simulation(report["incident_id"], proposed_action)
        st.session_state["simulation_notice"] = simulation_id
    if st.session_state.get("simulation_notice"):
        st.info(f"{st.session_state['simulation_notice']} · Preview recorded. No command was sent and no device was changed.")

    st.markdown("**Workflow checkpoint**")
    if st.button("Pause and save this run", key="pause_workflow"):
        checkpoint_id = workflow_store.save_checkpoint(
            st.session_state.get("current_scenario", scenario),
            st.session_state.get("current_payload"),
            st.session_state.get("current_result"),
            phase="paused",
        )
        st.session_state["checkpoint_notice"] = checkpoint_id
        st.rerun()
    if st.session_state.get("checkpoint_notice"):
        st.success(f"Paused workflow saved: {st.session_state['checkpoint_notice']}. Resume it from the sidebar.")

    events = workflow_store.recent_events()
    if events["reviews"] or events["simulations"]:
        st.markdown("**Recent persisted review and simulation log**")
        for item in events["reviews"]:
            st.write(f"{item['created_at']} · Review {item['review_id']} · {item['decision']}")
        for item in events["simulations"]:
            st.write(f"{item['created_at']} · Simulation {item['simulation_id']} · {item['action']} · {item['result']}")

