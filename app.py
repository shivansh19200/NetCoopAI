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
        "gateway": (70, 188), "router": (300, 188), "switch": (535, 82),
        "access_point": (790, 78), "service": (535, 330), "device": (790, 310),
    }
    coords = {}
    for i, node in enumerate(nodes):
        kind = str(node.get("type", "device")).lower()
        base = positions.get(kind, (650, 300))
        same = sum(1 for n in nodes[:i] if n.get("type") == kind)
        coords[str(node.get("id", f"node_{i}"))] = (base[0], base[1] + same * 65)
    lines, packets, labels = [], [], []
    for i, link in enumerate(links):
        a, b = coords.get(str(link.get("source"))), coords.get(str(link.get("target")))
        if not a or not b: continue
        d = f"M {a[0]+77} {a[1]+27} C {(a[0]+b[0])/2} {a[1]+27}, {(a[0]+b[0])/2} {b[1]+27}, {b[0]} {b[1]+27}"
        try: utilization = float(link.get("utilization_pct", 0) or 0)
        except (TypeError, ValueError): utilization = 0.0
        high = utilization >= 70 or str(link.get("target")) in highlighted
        color = "#8b72ff" if high else "url(#current-flow)"
        lines.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.5 if high else 1.5}"/>')
        packets.append(f'<circle r="3.5" fill="{"#b49cff" if high else "#42a9f5"}"><animateMotion dur="{3.2 + i*.65}s" begin="-{i*.7}s" repeatCount="indefinite" path="{d}"/></circle>')
        midx, midy = (a[0]+b[0]+77)/2, (a[1]+b[1]+54)/2 - 10
        labels.append(f'<text x="{midx}" y="{midy}" class="load">{utilization:.0f}%</text>')
    cards = []
    for node in nodes:
        node_key = str(node.get("id", ""))
        x, y = coords.get(node_key, (0, 0))
        is_hot = node_key in highlighted
        color = "#a58aff" if is_hot else "#42a9f5"
        label = escape(str(node.get("label", node.get("id", "Node")))[:22])
        node_id = escape(str(node.get("id", ""))[:20])
        cards.append(f'<g><rect x="{x}" y="{y}" width="154" height="54" rx="12" fill="#1a1624" stroke="{color}" stroke-width="{2 if is_hot else 1}"/><circle cx="{x+15}" cy="{y+18}" r="4" fill="{color}"/><text x="{x+27}" y="{y+22}" class="label">{label}</text><text x="{x+14}" y="{y+43}" class="id">{node_id}</text></g>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="470" viewBox="0 0 1000 470" role="img" aria-label="Network topology with animated packet flow">
    <title>Network topology</title>
    <defs>
      <radialGradient id="topology-bg" cx="45%" cy="45%"><stop offset="0%" stop-color="#211a30"/><stop offset="75%" stop-color="#1b1728"/></radialGradient>
      <linearGradient id="current-flow" x1="0" y1="1" x2="1" y2="0"><stop offset="0%" stop-color="#077ac7"/><stop offset="100%" stop-color="#6b21ef"/></linearGradient>
      <style>.label{{font:500 13px Arial,sans-serif;fill:#ffffff}}.id{{font:10px monospace;fill:#c5bec8}}.load{{font:12px monospace;fill:#d1cece}}</style>
    </defs>
    <rect x="1" y="1" width="998" height="468" rx="16" fill="url(#topology-bg)" stroke="#3e3a46"/>
    <circle cx="760" cy="28" r="5" fill="#42a9f5"/><text x="772" y="33" fill="#d1cece" font-family="monospace" font-size="12">PACKET FLOW</text>
    <circle cx="890" cy="28" r="5" fill="#a58aff"/><text x="902" y="33" fill="#d1cece" font-family="monospace" font-size="12">AFFECTED</text>
    {''.join(lines)}{''.join(labels)}{''.join(packets)}{''.join(cards)}</svg>'''


st.set_page_config(page_title="NetCoop AI | Network diagnosis", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@font-face{font-family:Manrope;src:url('/app/static/fonts/Manrope.ttf') format('truetype');font-weight:200 800;font-style:normal;font-display:swap}
@font-face{font-family:'DM Mono';src:url('/app/static/fonts/DMMono-Regular.ttf') format('truetype');font-weight:400;font-display:swap}
@font-face{font-family:'DM Mono';src:url('/app/static/fonts/DMMono-Medium.ttf') format('truetype');font-weight:500;font-display:swap}
html,body,[class*="css"]{font-family:'Manrope',sans-serif}
.stApp{background:radial-gradient(ellipse at 80% 0%,#20162a 0%,#0e0918 42%,#0e0918 100%);color:#d1cece}
.block-container{padding-top:1.4rem;padding-bottom:4rem;max-width:1200px}
[data-testid="stHeader"]{background:#0e0918}
[data-testid="stSidebar"]{background:#0e0918;border-right:1px solid #3e3a46;color:#d1cece}
[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3{color:#fff!important;font-weight:500!important;letter-spacing:-.02em}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#c5bec8!important}
.brandbar{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #3e3a46;padding:14px 2px 18px;margin-bottom:30px}
.brandmark{color:#fff;font-size:.85rem;font-weight:500;letter-spacing:.12em;text-transform:uppercase}
.brandmark span{color:#d1cece}
.brandmeta{color:#9d9797;font:500 .68rem 'DM Mono',monospace;letter-spacing:.08em}
.eyebrow{color:#9d9797;text-transform:uppercase;letter-spacing:.16em;font:500 .7rem 'DM Mono',monospace;text-align:center}
.hero-title{color:#fff;font:300 clamp(3rem,6vw,4.5rem)/.98 'Manrope',sans-serif;letter-spacing:-.045em;text-align:center;margin:.45rem 0 .5rem;text-shadow:none}
.hero-sub{color:#d1cece;font:400 clamp(1rem,2vw,1.2rem)/1.5 'Manrope',sans-serif;letter-spacing:.02em;text-align:center;text-transform:none;margin:.2rem 0 1.15rem}
.hero-status{width:fit-content;margin:0 auto 1.1rem;padding:.5rem 1rem;border:1px solid #3e3a46;border-radius:999px;background:#1a1624;box-shadow:inset 0 0 0 1px #ffffff0a;color:#d1cece;font:500 .75rem 'Manrope',sans-serif;letter-spacing:.04em;text-align:center}
.pill{display:inline-flex;gap:.45rem;align-items:center;padding:.38rem .72rem;background:#2c2834;border:1px solid #3e3a46;border-radius:8px;color:#d1cece;font:.7rem 'DM Mono',monospace}
.dot{width:7px;height:7px;border-radius:50%;background:#7b55ef;box-shadow:0 0 10px #7b55ef88}
.scoreboard{background:#1a1624;border:0;border-radius:16px;padding:24px 28px 22px;margin:1.8rem 0 1.3rem;box-shadow:inset 0 0 0 1px #ffffff1a,inset 0 -1px 0 #ff8e5d4d}
.scorelabel{color:#d1cece;font-size:.8rem;font-weight:500}
.scorevalue{font:400 2.5rem/1.05 'Manrope',sans-serif;letter-spacing:-.035em;margin:.35rem 0;color:#fff}
.scoremeta{color:#b5abbc;font:.68rem 'DM Mono',monospace;text-transform:uppercase;letter-spacing:.06em}
.redtext{color:#ff776c!important}.bluetext{color:#56b8ff!important}
.scoreline{height:4px;border-radius:8px;background:linear-gradient(141deg,#077ac7,#6b21ef);margin:1.1rem 0 .65rem;box-shadow:none}
.source-note{text-align:center;color:#9d9797;font:.68rem 'DM Mono',monospace;letter-spacing:.03em;margin:.7rem 0 1.8rem}
.metric-card{position:relative;background:#1a1624;border:0;border-radius:16px;padding:17px 18px 15px;min-height:105px;overflow:hidden;box-shadow:inset 0 0 0 1px #ffffff1a,inset 0 -1px 0 #ff8e5d4d}
.metric-card:before{content:'';position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(141deg,#077ac7,#6b21ef)}
.metric-label{color:#b5abbc;font:.68rem 'DM Mono',monospace;letter-spacing:.08em;text-transform:uppercase}
.metric-value{color:#fff;font:400 1.65rem/1.15 'Manrope',sans-serif;letter-spacing:-.025em;margin-top:7px;overflow-wrap:anywhere}
.metric-note{color:#b8b0bd;font-size:.72rem;margin-top:4px}
.section-title{color:#fff;font:500 1.45rem/1.2 'Manrope',sans-serif;letter-spacing:-.025em;text-transform:none;text-shadow:none}
.section-note{color:#b5abbc;font-size:.78rem;line-height:1.55}
.agent-chip{background:#1b1728;border:0;border-radius:16px;padding:16px 14px;height:100%;box-shadow:inset 0 0 0 1px #ffffff1a,inset 0 -1px 0 #ff8e5d4d}
.agent-chip strong{color:#fff;font-size:.82rem;font-weight:500}
.agent-chip small{display:block;color:#b5abbc;margin-top:6px;font-size:.72rem}
.mono{font-family:'DM Mono',monospace}
div[data-testid="stExpander"]{border:1px solid #3e3a46;border-radius:12px;background:#1a1624}
div[data-testid="stDataFrame"]{border:1px solid #3e3a46;border-radius:12px;overflow:hidden}
div[data-testid="stDownloadButton"] button,[data-testid="stButton"] button[kind="primary"]{background:linear-gradient(30deg,rgb(253,137,37),rgb(255,12,0));color:#fff;border:0;font-weight:500;letter-spacing:.01em;border-radius:8px}
[data-testid="stButton"] button{border-radius:8px;border-color:#68616f;background:#171322;color:#d1cece}
[data-testid="stButton"] button:hover{border-color:#8b7ba2;color:#fff}
[data-testid="stBaseButton-primary"]:hover{filter:brightness(1.08)}
[data-testid="stTabs"] button{color:#b5abbc}
[data-testid="stTabs"] button[aria-selected="true"]{color:#fff;border-bottom-color:#6b21ef}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stSelectbox"] [role="combobox"],[data-testid="stFileUploader"] section{background:#1a1624;color:#d1cece;border-color:#3e3a46;border-radius:8px}
.stAlert{border-radius:12px;background:#1b1728}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_demo():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return build_demo_data()


@st.cache_data(show_spinner=False)
def cached_diagnosis(payload, transport=None):
    return run_diagnosis(payload,agent_transport=transport)


def safe_diagnosis(payload):
    try:
        return cached_diagnosis(payload,os.environ.get("NETCOOP_AGENT_URL")), None
    except Exception as exc:
        return None, f"We couldn't finish this diagnosis. Check the telemetry format and try again. ({type(exc).__name__})"


def safe_groq_diagnosis(payload, api_key):
    try:
        from netcoop.model_agent import review_diagnosis

        reviewer = lambda report, messages: review_diagnosis(report, messages, api_key)
        hypothesizer = lambda messages: generate_hypotheses(messages, api_key)
        from netcoop.model_agent import generate_hypotheses
        return run_diagnosis(payload, model_reviewer=reviewer,model_hypothesizer=hypothesizer), None
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
    groq_enabled = st.checkbox("Get AI suggestions and summary", value=False, help="AI can suggest possible causes and write a summary. The evidence rules still decide the final result.")
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_api_key:
        try:
            groq_api_key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:
            groq_api_key = ""
    groq_review_clicked = False
    if groq_enabled:
        st.caption("When you request a review, readings and findings are sent to Groq. Do not use sensitive telemetry.")
        if not groq_api_key:
            st.warning("Set GROQ_API_KEY in the environment or Streamlit secrets to enable model review.")
        groq_review_clicked = st.button("Get AI suggestions", disabled=not bool(groq_api_key), width="stretch")
    st.caption(("Evidence rules + optional AI suggestions" if groq_enabled else "Evidence-based diagnosis") + " · sample readings")
    if "scenario" not in st.session_state:
        st.session_state["scenario"] = "link_congestion"
    scenario = st.selectbox("Demo scenario", SCENARIOS, format_func=lambda value: SCENARIO_LABELS.get(value, value), key="scenario", on_change=clear_active_checkpoint)
    run_clicked = st.button("▶  Run diagnosis", type="primary", width="stretch")
    st.divider()
    st.markdown("**Bring your own telemetry**")
    uploaded = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], help="JSON accepts a record or {records, topology}; CSV accepts one device per row.")
    st.markdown("---")
    st.markdown("**Dataset source**")
    st.caption("`data/sample_telemetry.json` · seed `20261031` · Colab-derived synthetic readings")
    st.markdown("**Try different readings**")
    what_if_enabled=st.checkbox("Apply what-if values",value=False,key="what_if_enabled")
    what_util=st.slider("Link utilization (%)",0,100,60,key="what_if_util")
    what_drops=st.slider("Queue drops",0,500,20,key="what_if_drops")
    what_rssi=st.slider("Signal strength (dBm)",-100,-30,-65,key="what_if_rssi")
    if st.button("Test changed field names and units",key="corrupt_input",width="stretch"):
        st.session_state["corrupt_input_enabled"]=not st.session_state.get("corrupt_input_enabled",False)

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

if payload is not None and what_if_enabled:
    what_records=payload.get("records",[]) if isinstance(payload,dict) else payload
    if isinstance(what_records,list):
        for row in what_records:
            if isinstance(row,dict):
                row.setdefault("metrics",{}).update({"link_utilization_pct":what_util,"queue_drops":what_drops,"signal_strength_dbm":what_rssi})
if payload is not None and st.session_state.get("corrupt_input_enabled"):
    corrupt_records=payload.get("records",[]) if isinstance(payload,dict) else payload
    if isinstance(corrupt_records,list) and corrupt_records and isinstance(corrupt_records[0],dict):
        row=corrupt_records[0]; metrics=row.setdefault("metrics",{})
        if "link_utilization_pct" in metrics: metrics["link_utilization"]=metrics.pop("link_utilization_pct")/100; row.setdefault("units",{})["link_utilization"]="fraction"
        if "latency_ms" in metrics: metrics["latency"]=metrics.pop("latency_ms")/1000; row.setdefault("units",{})["latency"]="s"

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
if uploaded is not None: st.info("Uploaded telemetry is active and overrides the selected demo scenario.", icon=":material/upload_file:")
diagnosed = report["status"] == "diagnosed"
ambiguous = report["status"] == "ambiguous"
status_label = "AMBIGUOUS" if ambiguous else "PROBABLE CAUSE IDENTIFIED" if diagnosed else "NOT ENOUGH EVIDENCE"
cause_label = report["suspected_root_cause"]
confidence_label = f"{report['confidence']:.0%}"
confidence_word = "High" if report["confidence"] >= .75 else "Medium" if report["confidence"] >= .45 else "Low"
model_review_active = report.get("model_review", {}).get("status") == "reviewed"
confidence_note = f"{confidence_word} · {'AI-assisted summary' if model_review_active else 'evidence rules'}"
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
.diagnosis-panel{{background:#1b1728;border:0;border-radius:24px;padding:28px 30px 24px;margin:1rem 0 1.35rem;box-shadow:inset 0 0 0 1px #ffffff1a,inset 0 -1px 0 #ff8e5d4d}}
.diag-top{{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #3e3a46;padding-bottom:16px}}
.diag-kicker{{color:#b5abbc;font:500 .68rem 'DM Mono',monospace;letter-spacing:.08em;text-transform:uppercase}}
.diag-status{{padding:6px 11px;border-radius:999px;background:#2c2834;border:1px solid #51465d;color:#e3d9f4;font:500 .68rem 'DM Mono',monospace;letter-spacing:.04em}}
.diag-main{{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:20px;align-items:center;padding:24px 0 18px}}
.diag-label{{color:#9d9797;font:500 .68rem 'DM Mono',monospace;letter-spacing:.1em;text-transform:uppercase}}
.diag-cause{{color:#fff;font:400 clamp(1.7rem,3.4vw,2.7rem)/1.15 'Manrope',sans-serif;letter-spacing:-.035em;margin:7px 0 0;overflow-wrap:anywhere}}
.diag-confidence{{text-align:right;border-left:1px solid #3e3a46;padding-left:18px}}
.diag-confidence b{{display:block;color:{confidence_color};font:400 2.1rem/1 'Manrope',sans-serif;letter-spacing:-.04em}}
.diag-confidence small{{display:block;color:#b5abbc;font:.65rem 'DM Mono',monospace;margin-top:7px;text-transform:uppercase;letter-spacing:.04em}}
.diag-evidence{{display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 20px}}
.diag-signal{{min-width:150px;flex:1;background:#1a1624;border:0;border-radius:12px;padding:13px 14px;box-shadow:inset 0 0 0 1px #ffffff12}}
.diag-signal span,.diag-signal small{{display:block;color:#b5abbc;font:.64rem 'DM Mono',monospace;text-transform:uppercase;letter-spacing:.04em}}
.diag-signal b{{display:block;color:#f4f0f5;font-size:.9rem;font-weight:500;margin:5px 0}}
.diag-empty{{color:#c5bec8;font-size:.8rem;padding:8px 0}}
.diag-bottom{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;border-top:1px solid #3e3a46;padding-top:16px;color:#c5bec8;font-size:.75rem;line-height:1.6}}
.diag-next{{color:#eee8f1;max-width:68%;margin-top:4px}}
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
def max_metric(name):
    values = [m[name] for m in all_metrics if isinstance(m.get(name), (int, float))]
    return max(values) if values else None

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
penalty_total=sum(report["confidence_breakdown"].get("penalties",{}).values())+report["confidence_breakdown"].get("agent_failures",0)
confidence_detail=f"Base {report['confidence_breakdown'].get('base',0):.0%} − penalties {penalty_total:.0%} · High ≥75%, Medium ≥45%"
with cols[1]: metric_card("Confidence", report["confidence"] * 100, confidence_detail, "%")
with cols[2]: metric_card("Latency", max_metric("latency_ms"), "Highest device reading", " ms")
with cols[3]: metric_card("Packet loss", max_metric("packet_loss_pct"), "Highest device reading", "%")
if experience == "Expert":
    with cols[4]: metric_card("CPU", max_metric("cpu_utilization_pct"), "Highest device reading", "%")
    with cols[5]: metric_card("Agent handoffs", len(result["agent_messages"]), "Validated messages")

trace_tab, json_tab = st.tabs(["Agent messages · replay", "JSON report"])
with trace_tab:
    trace = result["agent_messages"]
    selected_trace = st.slider("Replay messages", 1, max(1, len(trace)), len(trace), key="trace_replay")
    for message in trace[:selected_trace]:
        st.markdown(f"**{message['source_agent']} → {message['target_agent']}** · `{message['message_type']}` · {message['timestamp']}")
        summary = message["findings"][0] if message["findings"] else "No finding text"
        st.caption(f"{summary} · {len(message['evidence'])} evidence items · message {message['message_id'][:8]}")
        if message.get("normalization"):
            st.caption("Normalized: " + "; ".join(f"{n['field']} {n.get('from')} → {n.get('to')}" for n in message["normalization"]))
with json_tab:
    st.json(report, expanded=True)

st.markdown('<div class="section-title">Live network topology</div><div class="section-note">Animated packets follow the monitored paths. Highlight shows observed faults and downstream blast radius.</div>', unsafe_allow_html=True)
topology=result["topology"] or demo["topology"]
highlighted=set(report["affected_devices"])|{e["device_id"] for e in report["supporting_evidence"]}
if topology.get("devices"):
    st.image(render_topology(topology,highlighted),width="stretch",alt="Network topology highlighting fault evidence and downstream affected devices")
else: st.info("No usable topology was supplied. Add devices and links in the uploaded JSON to map the affected segment.")

left, right = st.columns([1.65, 1], gap="large")
with left:
    st.markdown('<div class="section-title">Telemetry snapshot</div>', unsafe_allow_html=True)
    view_data = build_telemetry_view(records, experience)
    help_columns = {name: st.column_config.NumberColumn(name, help=metric_help[name], format="%.1f") for name in metric_help if name in view_data["columns"]} if experience == "Expert" else {}
    st.dataframe(pd.DataFrame(view_data["rows"], columns=view_data["columns"]), width="stretch", hide_index=True, column_config=help_columns, alt="Telemetry readings for selected network devices")
    st.markdown('<div class="section-title">Metric time windows</div><div class="section-note">Readings are ordered by timestamp; multiple samples are needed for meaningful trends.</div>', unsafe_allow_html=True)
    trend_specs = [("latency_ms",100),("packet_loss_pct",2),("link_utilization_pct",70),("cpu_utilization_pct",85),("signal_strength_dbm",-75)]
    trend_cols=st.columns(2)
    for index,(metric,threshold) in enumerate(trend_specs):
        points=[(r.get("timestamp") or f"sample {i+1}",r["metrics"][metric]) for i,r in enumerate(records) if metric in r.get("metrics",{})]
        if points:
            low=min([v for _,v in points]+[threshold]); high=max([v for _,v in points]+[threshold]); span=max(high-low,1)
            chart_h=64; chart_w=300; pad=5
            coords=[(pad+i*(chart_w-2*pad)/max(1,len(points)-1),pad+(high-v)/span*(chart_h-2*pad)) for i,(_,v) in enumerate(points)]
            path=" ".join(("M" if i==0 else "L")+f"{x:.1f},{y:.1f}" for i,(x,y) in enumerate(coords))
            threshold_y=pad+(high-threshold)/span*(chart_h-2*pad)
            dots="".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#b49cff"/>' for x,y in coords)
            spark=f'<svg viewBox="0 0 {chart_w} {chart_h}" role="img" aria-label="{metric} trend with threshold {threshold}"><rect width="100%" height="100%" rx="10" fill="#1a1624"/><line x1="0" y1="{threshold_y:.1f}" x2="{chart_w}" y2="{threshold_y:.1f}" stroke="#9d9797" stroke-dasharray="5 4"/><path d="{path}" fill="none" stroke="#7b55ef" stroke-width="2.5"/>{dots}</svg>'
            with trend_cols[index%2]: st.caption(f"{metric} · {len(points)} samples · threshold {threshold}"); st.markdown(spark,unsafe_allow_html=True)
    for window in report.get("time_window_analysis",[]):
        for trend in window.get("trend_and_rate",[]): st.caption(f"{window['device_id']} · {trend['metric']} {trend['trend']} at {trend['rate_per_second']} {trend['unit_per_second']}")
        for interface,count in window.get("interface_flapping",{}).items(): st.warning(f"{window['device_id']} · interface {interface} changed state {count} times in the window.")

with right:
    st.markdown('<div class="section-title">Diagnostic report</div><div class="section-note">Evidence-ranked recommendation for operator review</div>', unsafe_allow_html=True)
    if report["status"] == "diagnosed":
        st.success(report["suspected_root_cause"])
    else:
        st.warning("Insufficient evidence for a reliable root-cause claim")
    st.markdown(f"**Incident**  <span class='mono'>{report['incident_id']}</span> &nbsp; · &nbsp; **Confidence** {report['confidence']:.0%}", unsafe_allow_html=True)
    if report.get("narrative"):
        st.markdown("**AI-written summary · checked by evidence rules**")
        st.write(report["narrative"])
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

st.markdown('<div class="section-title">What each specialist found</div><div class="section-note">Specialists compare device readings and network connections, then share evidence for the final report.</div>', unsafe_allow_html=True)
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
                evidence_frame=pd.DataFrame(message["evidence"])
                if "value" in evidence_frame: evidence_frame["value"]=evidence_frame["value"].map(str)
                st.dataframe(evidence_frame, width="stretch", hide_index=True, alt=f"Evidence sent by {message['source_agent']}")
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
    st.caption("NetCoop AI · " + ("evidence rules + AI suggestions" if model_review_active else "evidence rules") + " · sample readings.")
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


