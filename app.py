from __future__ import annotations

import json
import hashlib
import os
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from netcoop.agents import run_diagnosis
from netcoop.dashboard_views import build_telemetry_view
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
        coords[str(node.get("id", f"node_{i}"))] = (base[0], base[1] + same * 54)
    lines, packets, labels = [], [], []
    for i, link in enumerate(links):
        a, b = coords.get(str(link.get("source"))), coords.get(str(link.get("target")))
        if not a or not b: continue
        d = f"M {a[0]+52} {a[1]+21} C {(a[0]+b[0])/2} {a[1]+21}, {(a[0]+b[0])/2} {b[1]+21}, {b[0]} {b[1]+21}"
        try: utilization = float(link.get("utilization_pct", 0) or 0)
        except (TypeError, ValueError): utilization = 0.0
        high = utilization >= 70 or str(link.get("target")) in highlighted
        color = "#ff623e" if high else "#08bff5"
        lines.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.5 if high else 1.5}"/>')
        packets.append(f'<circle r="3.5" fill="{"#ff9a39" if high else "#08bff5"}"><animateMotion dur="{3.2 + i*.65}s" begin="-{i*.7}s" repeatCount="indefinite" path="{d}"/></circle>')
        midx, midy = (a[0]+b[0]+52)/2, (a[1]+b[1]+42)/2 - 9
        labels.append(f'<text x="{midx}" y="{midy}" class="load">{utilization:.0f}%</text>')
    cards = []
    for node in nodes:
        node_key = str(node.get("id", ""))
        x, y = coords.get(node_key, (0, 0))
        is_hot = node_key in highlighted
        color = "#ff623e" if is_hot else "#08bff5"
        label = escape(str(node.get("label", node.get("id", "Node")))[:22])
        node_id = escape(str(node.get("id", ""))[:20])
        cards.append(f'<g><rect x="{x}" y="{y}" width="112" height="43" rx="10" fill="#151517" stroke="{color}" stroke-width="{1.7 if is_hot else 1}"/><circle cx="{x+13}" cy="{y+14}" r="3.5" fill="{color}"/><text x="{x+23}" y="{y+17}" class="label">{label}</text><text x="{x+12}" y="{y+33}" class="id">{node_id}</text></g>')
    return f'''<style>
    .netcoop-topology-frame{{height:420px;min-height:420px;border:1px solid #29292c;border-radius:14px;background:radial-gradient(ellipse at 45% 45%,#1b100d,#080808 70%);overflow:auto;position:relative;font-family:Manrope,Arial,sans-serif;color:#f1f1f1}}
    .netcoop-topology-frame svg{{display:block;width:100%;min-width:700px;height:400px}} .netcoop-topology-frame .label{{font-size:9px;fill:#eeeeef;font-weight:700}} .netcoop-topology-frame .id{{font-size:7px;fill:#85858b;font-family:monospace}} .netcoop-topology-frame .load{{font-size:9px;fill:#aaa;font-family:monospace}}
    .netcoop-topology-frame .legend{{position:absolute;right:14px;top:13px;font-size:9px;color:#999;font-family:monospace;letter-spacing:.06em}} .netcoop-topology-frame .legend b{{color:#08bff5;font-weight:400}} .netcoop-topology-frame .key{{color:#ff623e!important}}
    </style><div class="netcoop-topology-frame"><div class="legend"><b>●</b> PACKET FLOW &nbsp; <b class="key">●</b> ELEVATED</div><svg viewBox="0 0 800 400" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Network topology with animated packet flow">{''.join(lines)}{''.join(labels)}{''.join(packets)}{''.join(cards)}</svg></div>'''


st.set_page_config(page_title="NetCoop AI | Deterministic rule-based agents", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

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


def safe_diagnosis(payload):
    try:
        return cached_diagnosis(payload), None
    except Exception as exc:
        return None, f"We couldn't finish this diagnosis. Check the telemetry format and try again. ({type(exc).__name__})"


def safe_groq_diagnosis(payload, api_key):
    try:
        from netcoop.model_agent import review_diagnosis

        reviewer = lambda report, messages: review_diagnosis(report, messages, api_key)
        return run_diagnosis(payload, model_reviewer=reviewer), None
    except Exception as exc:
        return None, f"Groq review couldn't run ({type(exc).__name__}); use the deterministic diagnosis or check the API configuration."


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
    if hasattr(st, "segmented_control"):
        experience = st.segmented_control("Dashboard detail", ["Beginner", "Expert"], default="Beginner", key="dashboard_detail")
    else:
        experience = st.radio("Dashboard detail", ["Beginner", "Expert"], horizontal=True, key="dashboard_detail", help="Beginner summarizes readings in plain language. Expert shows raw metrics, units, and metric definitions.")
    groq_enabled = st.checkbox("Add Groq model reviewer", value=False, help="Optional model review of agent findings. The deterministic verdict and confidence remain authoritative.")
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_api_key:
        try:
            groq_api_key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:
            groq_api_key = ""
    groq_review_clicked = False
    if groq_enabled:
        st.caption("When you run review, the rule report and agent findings are sent to Groq. Do not enable this for sensitive telemetry.")
        if not groq_api_key:
            st.warning("Set GROQ_API_KEY in the environment or Streamlit secrets to enable model review.")
        groq_review_clicked = st.button("Review findings with Groq", disabled=not bool(groq_api_key), width="stretch")
    st.caption(("Deterministic rule-based agents + Groq advisory" if groq_enabled else "Deterministic rule-based agents") + " · repeatable synthetic telemetry")
    if "scenario" not in st.session_state:
        st.session_state["scenario"] = "link_congestion"
    scenario = st.selectbox("Demo scenario", SCENARIOS, format_func=lambda value: SCENARIO_LABELS.get(value, value), key="scenario", on_change=clear_active_checkpoint)
    run_clicked = st.button("▶  Run deterministic diagnosis", type="primary", width="stretch")
    st.divider()
    st.markdown("**Bring your own telemetry**")
    uploaded = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], help="JSON accepts a record or {records, topology}; CSV accepts one device per row.")
    st.markdown("---")
    st.markdown("**Dataset source**")
    st.caption("`data/sample_telemetry.json` · seed `20261031` · Colab-derived synthetic readings")

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
    analysis_record = {key: value for key, value in selected.items() if key != "scenario"} if selected else None
    payload = {"records": [analysis_record] if analysis_record else [], "topology": demo["topology"]}

active_checkpoint = st.session_state.get("active_checkpoint")
diagnosis_error = None
if active_checkpoint and uploaded is None and not input_error:
    payload = active_checkpoint["payload"]
    result = active_checkpoint["result"]
elif input_error:
    st.error(input_error)
    result, diagnosis_error = safe_diagnosis({})
else:
    result, diagnosis_error = safe_diagnosis(payload)
payload_fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest() if payload is not None else ""
if groq_enabled and groq_review_clicked and result is not None and payload is not None and not input_error:
    result, diagnosis_error = safe_groq_diagnosis(payload, groq_api_key)
    if result is not None:
        st.session_state["groq_review_fingerprint"] = payload_fingerprint
        st.session_state["groq_review_result"] = result
if groq_enabled and st.session_state.get("groq_review_fingerprint") == payload_fingerprint:
    result = st.session_state.get("groq_review_result", result)
if result is None:
    st.error(diagnosis_error or "We couldn't finish this diagnosis. Please review the input and retry.")
    st.stop()
report = result["report"]
st.session_state["current_payload"] = payload
st.session_state["current_result"] = result
st.session_state["current_scenario"] = scenario

scenario_record = records_by_scenario.get(scenario, {})
observed_devices = ", ".join(r["device_id"] for r in result["records"]) or "Awaiting telemetry"
scenario_heading = "UPLOADED TELEMETRY" if uploaded is not None else SCENARIO_LABELS.get(scenario, scenario).upper()
scenario_device = "UPLOADED DATA" if uploaded is not None else str(scenario_record.get("device_id", "SAMPLE RECORD"))
diagnosed = report["status"] == "diagnosed"
ambiguous = report["status"] == "ambiguous"
status_label = "AMBIGUOUS" if ambiguous else "PROBABLE CAUSE IDENTIFIED" if diagnosed else "NOT ENOUGH EVIDENCE"
cause_label = report["suspected_root_cause"]
confidence_label = f"{report['confidence']:.0%}"
confidence_word = "High" if report["confidence"] >= .75 else "Medium" if report["confidence"] >= .45 else "Low"
model_review_active = report.get("model_review", {}).get("status") == "reviewed"
confidence_note = f"{confidence_word} · {'Groq-reviewed' if model_review_active else 'deterministic rule-based agents'}"
confidence_color = "#54d38a" if confidence_word == "High" else "#ffc35c" if confidence_word == "Medium" else "#ff625e"
source_label = "Uploaded telemetry" if uploaded is not None else "Synthetic demo fixture"
visible_evidence = [item for item in report["supporting_evidence"] if item["metric"] != "topology_scope"][:3]
metric_help = {"latency_ms":"Time for a packet to travel, in milliseconds.","jitter_ms":"How much packet travel time varies.","queue_drops":"Packets discarded while waiting in a device queue.","packet_loss_pct":"Share of packets that did not arrive.","link_utilization_pct":"Share of link capacity currently in use.","signal_strength_dbm":"Radio signal strength; values closer to zero are stronger.","interface_errors":"Errors counted by a wired network port."}
def evidence_sentence(item):
    metric, value = item["metric"], item["value"]
    if metric == "link_utilization_pct": return f"Link is {value:g}% full; normal is under 70%."
    if metric == "cpu_utilization_pct": return f"Device CPU is {value:g}% busy; investigate above 85%."
    if metric == "queue_drops": return f"Device dropped {value:g} packets from its queue; investigate above 50."
    if metric == "packet_loss_pct": return f"{value:g}% of packets were lost; investigate above 2%."
    if metric == "latency_ms": return f"Packets took {value:g} ms; investigate above 100 ms."
    if metric == "signal_strength_dbm": return f"Wi-Fi signal was {value:g} dBm; weak below -75 dBm."
    if metric == "retransmissions_pct": return f"{value:g}% of Wi-Fi packets needed retransmission."
    if metric == "interface_errors": return f"Network port recorded {value:g} errors; investigate above 10."
    return item["interpretation"]
evidence_html = "".join(
    f'<div class="diag-signal"><span>{escape(str(item["metric"]).replace("_", " "))}</span><b>{escape(evidence_sentence(item))}</b><small>{escape(str(item["device_id"]))}</small></div>'
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
.diag-confidence b{{display:block;color:{confidence_color};font:800 2rem/1 'Barlow Condensed',sans-serif}}
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
  <div class="diag-main"><div><div class="diag-label">WHAT'S WRONG</div><div class="diag-cause">{escape(str(cause_label))}</div></div><div class="diag-confidence"><b>{confidence_label}</b><small>HOW SURE · {confidence_note}</small></div></div>
  <div class="diag-evidence">{evidence_html}</div>
  <div class="diag-bottom"><div><span class="diag-kicker">WHAT TO DO NEXT</span><div class="diag-next">{escape(str(next_step))}</div></div><div style="text-align:right"><span class="diag-kicker">SCENARIO</span><div>{escape(scenario_heading)} · {escape(scenario_device)}</div><span class="diag-kicker">AFFECTED</span><div>{escape(observed_devices)}</div><span class="diag-kicker">SOURCE</span><div>{source_label}</div></div></div>
</div>''', unsafe_allow_html=True)
if result["warnings"]:
    friendly_warnings = []
    for warning in result["warnings"]:
        lower = warning.lower()
        if "latency looked like seconds" in lower:
            friendly_warnings.append("Latency looked like seconds, so we ignored it; confidence is lower.")
        elif "0-1 fraction" in lower:
            friendly_warnings.append("A percentage looked like a 0-1 fraction, so we ignored it; confidence is lower.")
        elif "topology" in lower:
            friendly_warnings.append("Some topology details were missing or skipped, so affected network scope may be limited.")
    for note in dict.fromkeys(friendly_warnings): st.info(note)
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

st.caption(f"{experience} view · " + ("plain-language findings" if experience == "Beginner" else "raw measurements, units, and diagnostic scoring"))
cols = st.columns(6 if experience == "Expert" else 4)
with cols[0]: metric_card("Root cause", report["suspected_root_cause"].replace(" ", "\u00a0"), report["status"].replace("_", " ").title())
with cols[1]: metric_card("Confidence", report["confidence"] * 100, "Rule-based evidence score", "%")
with cols[2]: metric_card("Latency", mean_metric("latency_ms"), "Mean of available devices", " ms")
with cols[3]: metric_card("Packet loss", mean_metric("packet_loss_pct"), "Mean of available devices", "%")
if experience == "Expert":
    with cols[4]: metric_card("CPU", mean_metric("cpu_utilization_pct"), "Mean of available devices", "%")
    with cols[5]: metric_card("Agent handoffs", len(result["agent_messages"]), "Validated messages")

left, right = st.columns([1.65, 1], gap="large")
with left:
    st.markdown('<div class="section-title">Live network topology</div><div class="section-note">Animated packets follow the monitored paths. Highlight indicates the strongest observed fault signal.</div>', unsafe_allow_html=True)
    topology = result["topology"] or demo["topology"]
    warning_nodes = set(report["affected_devices"])
    metrics_to_highlight = {e["device_id"] for e in report["supporting_evidence"]}
    if topology.get("devices"):
        st.html(render_topology(topology, warning_nodes | metrics_to_highlight), width="stretch")
    else:
        st.info("No usable topology was supplied. Add devices and links in the uploaded JSON to map the affected segment.")
    st.markdown('<div class="section-title">Telemetry snapshot</div>', unsafe_allow_html=True)
    view_data = build_telemetry_view(records, experience)
    help_columns = {name: st.column_config.NumberColumn(name, help=metric_help[name], format="%.1f") for name in metric_help if name in view_data["columns"]} if experience == "Expert" else {}
    st.dataframe(pd.DataFrame(view_data["rows"], columns=view_data["columns"]), width="stretch", hide_index=True, column_config=help_columns, alt="Telemetry readings for selected network devices")

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
    if report.get("model_review"):
        st.markdown("**Groq reviewer · advisory only**")
        st.info(report["model_review"]["summary"])
        st.caption("It does not change the rule-based verdict or confidence.")
        if report["model_review"]["alternative_explanations"]:
            st.markdown("Possible alternatives: " + "; ".join(report["model_review"]["alternative_explanations"]))
        if report["model_review"]["recommended_checks"]:
            st.markdown("Suggested checks: " + "; ".join(report["model_review"]["recommended_checks"]))
    st.markdown("**Recommended next steps**")
    for action in report["recommended_actions"]:
        st.markdown(f"- {action}")
    if report["alternative_causes"]:
        with st.expander("Other possible causes"):
            for alternative in report["alternative_causes"]:
                st.write("• " + alternative)
    if report["limitations"]:
        with st.expander("Limitations and input notes"):
            for limitation in report["limitations"]:
                st.write("• " + limitation)

st.markdown('<div class="section-title">Agent findings</div><div class="section-note">Scenario label withheld · specialists analyze telemetry and topology · correlator compares their messages and ranks causes.</div>', unsafe_allow_html=True)
message_by_agent = {message["source_agent"]: message for message in result["agent_messages"]}
specialists = [
    ("performance_agent", "Performance", "Latency, jitter, loss, link use, Wi-Fi signal"),
    ("infrastructure_agent", "Infrastructure", "CPU, memory, queues, interfaces, device health"),
    ("connectivity_agent", "Connectivity", "Topology scope and network services"),
]
specialist_cols = st.columns(3)
for col, (agent_id, label, role) in zip(specialist_cols, specialists):
    message = message_by_agent.get(agent_id, {})
    with col, st.container(border=True):
        st.markdown(f"**{label} agent**")
        st.caption(role)
        if message.get("evidence"):
            for evidence_item in message["evidence"][:3]:
                st.write(f"{evidence_item['device_id']} · {evidence_item['metric']} **{evidence_item['value']} {evidence_item['unit']}**")
            if len(message["evidence"]) > 3:
                st.caption(f"+ {len(message['evidence']) - 3} more findings")
        else:
            st.write("No elevated readings found.")
correlator_message = message_by_agent.get("correlation_agent", {})
top_candidate = report.get("ranked_candidates", [])
correlation_summary = f"Compared {len(correlator_message.get('received_message_ids', []))} specialist messages"
if top_candidate:
    correlation_summary += f" · ranked {top_candidate[0]['cause']} first ({top_candidate[0]['score']:.0%})"
st.info(correlation_summary + f" · report confidence {report['confidence']:.0%}", icon=":material/account_tree:")

st.divider()
with st.expander("Technical details", expanded=False):
    st.markdown("**What is being evaluated?**")
    st.caption("The tests compare deterministic diagnosis rules with the expected labels for nine fixed-seed synthetic scenarios, and check malformed input, message validation, ties, mixed faults, duplicate records, and confidence penalties. This evaluates a rule-based prototype; its confidence score is not a learned-model benchmark.")
    st.markdown("**What each agent contributes**")
    st.caption("Each specialist sends a validated message. The correlator compares support across agents and sends its result to the report writer.")
    st.caption("Core system: deterministic rule-based agents. Demo readings are stored in data/sample_telemetry.json and generated with seed 20261031.")
    st.download_button("Download the full synthetic dataset", data=json.dumps(demo, indent=2), file_name="netcoop_synthetic_telemetry.json", mime="application/json")
    if uploaded is None and scenario_record:
        st.markdown("**Selected fixture record**")
        st.json(scenario_record, expanded=False)
    if experience == "Expert":
        st.markdown("**Metric guide**")
        for metric, explanation in metric_help.items(): st.caption(f"{metric}: {explanation}")
    st.markdown('<div class="section-title">Agent collaboration trace</div><div class="section-note">Specialist findings → evidence comparison → ranked diagnosis → report</div>', unsafe_allow_html=True)
    agents = [
    ("Performance", "Latency · loss · jitter · link load"),
    ("Infrastructure", "CPU · memory · queues · interfaces"),
    ("Connectivity", "Topology · scope · services"),
    ("Fault correlation", "Evidence families · competing causes"),
    ("Reporting", "Confidence · actions · JSON output"),
]
    if model_review_active:
        agents.append(("Groq reviewer", "Advisory evidence review"))
    agent_cols = st.columns(len(agents))
    for col, (name, subtitle) in zip(agent_cols, agents):
        with col:
            st.markdown(f'<div class="agent-chip"><strong>◉ &nbsp;{name}</strong><small>{subtitle}</small></div>', unsafe_allow_html=True)
    st.markdown("**How the agents reached this result**")
    for message in result["agent_messages"]:
        title = f"{message['source_agent'].replace('_', ' ').title()} → {message['target_agent'].replace('_', ' ').title()} · {message['status']}"
        with st.expander(title):
            for finding in message["findings"]:
                st.write(finding)
            if message["evidence"]:
                st.dataframe(pd.DataFrame(message["evidence"]), width="stretch", hide_index=True, alt=f"Evidence sent by {message['source_agent']}")
            else:
                st.caption("No supporting measurements found by this agent.")
            if message.get("received_message_ids"):
                st.caption(f"Compared {len(message['received_message_ids'])} specialist messages.")
            if experience == "Expert":
                st.json(message, expanded=False)
    if result["ranked_candidates"]:
        st.markdown("**Confidence breakdown and other possible causes**")
        st.json(report["confidence_breakdown"], expanded=False)
        st.dataframe(pd.DataFrame([{"Candidate": c["cause"], "Score": c["score"], "Signals": c["distinct_signals"]} for c in result["ranked_candidates"]]), width="stretch", hide_index=True, alt="Ranked possible causes and evidence scores")

    st.download_button("Download diagnostic report · JSON", data=json.dumps(report, indent=2), file_name=f"{report['incident_id'].lower()}_report.json", mime="application/json")
    st.caption("NetCoop AI · " + ("deterministic agents + Groq advisory" if model_review_active else "deterministic rule-based agents") + " · synthetic telemetry.")
    st.markdown("**Schema warnings**")
    if result["warnings"]:
        for warning in result["warnings"]: st.warning(warning)
    else: st.caption("No input warnings.")
    st.caption("Optional MCP server: run `mcp run mcp_server.py` for local tool access.")

    st.markdown("**Human review · pause/resume · remediation simulation**")
    checkpoint_options = [""] + [item["checkpoint_id"] for item in saved_checkpoints]
    st.selectbox("Saved checkpoints", checkpoint_options, key="resume_choice", format_func=lambda key: "Choose saved run" if not key else next((f"{item['checkpoint_id']} · {item['scenario']} · {item['phase']}" for item in saved_checkpoints if item["checkpoint_id"] == key), key))
    st.button("Resume selected checkpoint", on_click=resume_checkpoint_callback, width="stretch", disabled=not bool(saved_checkpoints))
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
        checkpoint_id = workflow_store.save_checkpoint(st.session_state.get("current_scenario", scenario), st.session_state.get("current_payload"), st.session_state.get("current_result"), phase="paused")
        st.session_state["checkpoint_notice"] = checkpoint_id
        st.rerun()
    if st.session_state.get("checkpoint_notice"):
        st.success(f"Paused workflow saved: {st.session_state['checkpoint_notice']}. Resume it from the controls above.")

    events = workflow_store.recent_events()
    if events["reviews"] or events["simulations"]:
        st.markdown("**Recent persisted review and simulation log**")
        for item in events["reviews"]: st.write(f"{item['created_at']} · Review {item['review_id']} · {item['decision']}")
        for item in events["simulations"]: st.write(f"{item['created_at']} · Simulation {item['simulation_id']} · {item['action']} · {item['result']}")

