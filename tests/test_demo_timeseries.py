from datetime import datetime

from netcoop.data_generator import build_demo_timeseries


def test_dashboard_history_has_timestamped_jittered_series():
    history = build_demo_timeseries()
    assert len(history["records"]) == 86
    assert history["synthetic_history"]["samples_per_scenario"] == 12
    for scenario in history["synthetic_history"]["series_scenarios"]:
        rows = [r for r in history["records"] if r.get("scenario") == scenario]
        assert len(rows) == 12
        assert len({r["device_id"] for r in rows}) == 1
        timestamps = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rows]
        assert timestamps == sorted(timestamps)
        assert all((b-a).total_seconds() == 240 for a,b in zip(timestamps,timestamps[1:]))
    link_values = [r["metrics"]["link_utilization_pct"] for r in history["records"] if r.get("scenario") == "link_congestion"]
    assert len(set(link_values)) > 1
