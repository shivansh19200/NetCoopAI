from copy import deepcopy
from datetime import datetime, timedelta, timezone

from netcoop.agents import run_diagnosis
from netcoop.data_generator import build_demo_timeseries


def _diagnose_with_values(history, utilization, drops, signal):
    rows = deepcopy([r for r in history["records"] if r.get("scenario") == "link_congestion"])
    for row in rows:
        row["metrics"].update(link_utilization_pct=utilization, queue_drops=drops, signal_strength_dbm=signal)
    return run_diagnosis({"records": rows, "topology": history["topology"]})["report"]


def test_what_if_values_change_supported_cause_and_confidence():
    history = build_demo_timeseries()
    low = _diagnose_with_values(history, 60, 20, -65)
    high = _diagnose_with_values(history, 100, 500, -30)
    assert low["suspected_root_cause"] != high["suspected_root_cause"]
    assert high["confidence"] > low["confidence"]
    assert high["confidence_breakdown"]["penalties"]["stale_telemetry"] == 0


def test_stale_uploaded_readings_earn_a_visible_confidence_penalty():
    history = build_demo_timeseries()
    rows = deepcopy([r for r in history["records"] if r.get("scenario") == "link_congestion"])
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
    for index, row in enumerate(rows):
        row["timestamp"] = (stale_time + timedelta(minutes=index*4)).isoformat().replace("+00:00", "Z")
    report = run_diagnosis({"records": rows, "topology": history["topology"]})["report"]
    assert report["confidence_breakdown"]["penalties"]["stale_telemetry"] == .1
