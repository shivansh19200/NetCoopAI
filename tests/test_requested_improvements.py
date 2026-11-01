from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from netcoop.agents import normalize_records, run_diagnosis
from netcoop.dashboard_views import confidence_explanation, distinct_problem_count, warning_summary


ROOT = Path(__file__).resolve().parents[1]


def record(device_id="EDGE", metrics=None, **overrides):
    row = {
        "device_id": device_id,
        "device_type": "switch",
        "site": "Test segment",
        "status": "Warning",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics or {},
    }
    row.update(overrides)
    return row


def test_fixture_report_ignores_as_of_for_staleness():
    fixture = json.loads((ROOT / "data" / "sample_telemetry.json").read_text(encoding="utf-8"))
    first = run_diagnosis(fixture, as_of=datetime(1999, 1, 1, tzinfo=timezone.utc), seed=7,
                          deterministic_ids=True)["report"]
    second = run_diagnosis(fixture, as_of=datetime(2099, 1, 1, tzinfo=timezone.utc), seed=7,
                           deterministic_ids=True)["report"]
    assert first == second


def test_percent_values_remain_percent_without_unit_hints():
    normalized, warnings, _ = normalize_records([record(metrics={
        "packet_loss_pct": 0.5, "link_utilization_pct": 1, "cpu_utilization_pct": 0.2,
    })])
    assert normalized[0]["metrics"] == {
        "packet_loss_pct": 0.5, "link_utilization_pct": 1, "cpu_utilization_pct": 0.2,
    }
    assert not any("fraction" in warning for warning in warnings)
    report = run_diagnosis({"records": [record(status="Healthy", metrics={
        "packet_loss_pct": 0.5, "link_utilization_pct": 1, "cpu_utilization_pct": 0.2,
    })]})["report"]
    assert report["status"] == "healthy"


def test_fraction_units_are_case_insensitive_and_trimmed():
    normalized, _, _ = normalize_records([record(metrics={"packet_loss_pct": 0.5}, units={"packet_loss_pct": " FRACTION "})])
    assert normalized[0]["metrics"]["packet_loss_pct"] == 50


def test_explicit_fraction_hint_warns_and_penalizes_inferred_fields():
    normalized, warnings, _ = normalize_records([record(
        metrics={"cpu_utilization_pct": 0.2, "memory_utilization_pct": 0.3},
        units={"cpu_utilization_pct": "fraction"},
    )])
    assert normalized[0]["metrics"]["cpu_utilization_pct"] == 20
    assert normalized[0]["metrics"]["memory_utilization_pct"] == 30
    assert any(item.get("confidence_penalty") == .05 for item in normalized[0]["normalization"])
    assert any("treated as fractions" in warning for warning in warnings)


def test_healthy_status_gets_coverage_confidence():
    result = run_diagnosis({"records": [record(status="Healthy", metrics={
        "latency_ms": 20, "link_utilization_pct": 30, "packet_loss_pct": 0.1,
    })]})["report"]
    assert result["status"] == "healthy"
    assert result["suspected_root_cause"] == "No fault detected"
    assert result["confidence"] >= .8


def test_dns_outage_and_switch_congestion_make_two_incidents():
    records = [
        record("SW1", {"link_utilization_pct": 95, "queue_drops": 150, "latency_ms": 180, "packet_loss_pct": 4}, site="Core"),
        record("DNS1", {"service_status": 0}, device_type="service", status="Critical", site="Services"),
    ]
    result = run_diagnosis({"records": records, "topology": {"devices": [{"id": "SW1"}, {"id": "DNS1"}], "links": []}})["report"]
    assert {(item["device_ids"][0], item["cause"]) for item in result["incidents"]} == {
        ("SW1", "Link congestion"), ("DNS1", "DNS/DHCP service failure")
    }
    assert result["suspected_root_cause"] == "DNS/DHCP service failure"


def test_duplicate_warning_is_aggregated_and_warnings_are_capped():
    row = record(metrics={"unknown_metric": 1})
    normalized, warnings, _ = normalize_records([row] * 500)
    assert len(normalized) == 1
    duplicate_warning = next(warning for warning in warnings if "duplicate record" in warning)
    assert "499" in duplicate_warning
    _, capped, _ = normalize_records([record(device_id=f"bad-{i}", metrics={f"unknown-{i}": 1}) for i in range(200)])
    assert len(capped) == 50
    assert "+" in capped[-1]


def test_deterministic_mode_makes_json_and_ids_repeatable():
    payload = {"records": [record(metrics={"link_utilization_pct": 90, "queue_drops": 80, "latency_ms": 160})]}
    first = run_diagnosis(payload, seed="demo", deterministic_ids=True)
    second = run_diagnosis(payload, seed="demo", deterministic_ids=True)
    assert first["messages_json"] == second["messages_json"]
    assert first["report"] == second["report"]


def test_five_thousand_device_diagnosis_meets_runtime_budget():
    payload = {"records": [record(f"device-{i}", {}) for i in range(5000)]}
    started = time.perf_counter()
    result = run_diagnosis(payload)
    elapsed = time.perf_counter() - started
    assert len(result["records"]) == 5000
    assert elapsed < 1.5


def test_stale_clear_hardware_signature_retains_high_confidence():
    stale = (datetime.now(timezone.utc) - timedelta(hours=1, seconds=5)).isoformat()
    report = run_diagnosis({"records": [record(
        metrics={"cpu_utilization_pct": 99, "interface_errors": 250},
        status="Critical", timestamp=stale,
    )]})["report"]
    assert report["suspected_root_cause"] == "Hardware failure"
    assert report["confidence"] >= .7


def test_low_confidence_has_distinct_status():
    stale = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    row = record(metrics={
        "link_utilization_pct": .95, "queue_drops": 200, "latency_ms": 250,
        "packet_loss_pct": .04, "cpu_utilization_pct": .2, "memory_utilization_pct": .3,
        **{f"unknown_{i}": 1 for i in range(10)},
    }, status="Warning", timestamp=stale, units={"cpu_utilization_pct": "fraction"}, schema_version="legacy")
    report = run_diagnosis({"records": [row], "schema_version": "legacy"})["report"]
    assert report["confidence"] < .3
    assert report["status"] == "low_confidence"


def test_beginner_dashboard_summaries_hide_formula_and_dedupe_pairs():
    report = {
        "status": "diagnosed",
        "confidence": .6,
        "supporting_evidence": [
            {"device_id": "SW1", "metric": "queue_drops"},
            {"device_id": "SW1", "metric": "queue_drops"},
            {"device_id": "SW1", "metric": "latency_ms"},
        ],
        "confidence_breakdown": {"penalties": {"stale_telemetry": .1}},
    }
    assert distinct_problem_count(report) == 2
    assert "old" in confidence_explanation(report)
    assert "Base" not in confidence_explanation(report)
    assert "499 duplicate readings ignored" in warning_summary(["499 duplicate record(s) ignored."])
