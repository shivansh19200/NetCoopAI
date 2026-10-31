"""Regression tests requested for the deterministic rule-based agents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import netcoop.agents as agents
from netcoop.data_generator import SCENARIOS, build_demo_data
from netcoop.dashboard_views import build_telemetry_view
from netcoop.model_agent import GROQ_MODEL, review_diagnosis

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs" / "schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def demo():
    return build_demo_data()


def one_record(metrics, *, device="EDGE_1", status="Warning", device_type="switch", timestamp="2026-10-31T00:00:00Z"):
    return {
        "timestamp": timestamp,
        "device_id": device,
        "device_type": device_type,
        "site": "Test segment",
        "status": status,
        "metrics": metrics,
    }


def envelope(source, evidence, *, target="correlation_agent", findings=None):
    return {
        "schema_version": agents.PROTOCOL,
        "message_id": f"msg-{source}",
        "timestamp": "2026-10-31T00:00:00Z",
        "source_agent": source,
        "target_agent": target,
        "status": "ok",
        "findings": findings or [f"{source} finding"],
        "evidence": evidence,
        "limitations": [],
    }


def ev(metric, value, unit, device="EDGE_1"):
    return {"device_id": device, "metric": metric, "value": value, "unit": unit, "interpretation": f"Observed {metric}"}


def test_nine_synthetic_scenarios_have_documented_verdicts(demo):
    expected = {
        "normal": "insufficient_evidence",
        "latency_spike": "Latency spike",
        "hardware_failure": "Hardware failure",
        "link_congestion": "Link congestion",
        "weak_wifi": "Weak Wi-Fi",
        "interface_fault": "Ethernet/interface fault",
        "dns_dhcp_failure": "DNS/DHCP service failure",
        "interoperability_failure": "Link congestion",
        "malformed_input": "insufficient_evidence",
    }
    assert SCENARIOS == list(expected)
    for record in demo["records"]:
        result = agents.run_diagnosis({"records": [record], "topology": demo["topology"]})["report"]
        verdict = result["suspected_root_cause"] if result["status"] == "diagnosed" else result["status"]
        assert verdict == expected[record["scenario"]], record["scenario"]


@pytest.mark.parametrize("topology", [[], "bad topology", None, {"devices": [None, 4], "links": ["bad", None]}, {"devices": None, "links": {}}])
def test_malformed_topology_is_sanitized_with_warning(topology):
    result = agents.run_diagnosis({"records": [one_record({"latency_ms": 180})], "topology": topology})
    assert isinstance(result["topology"], dict)
    assert isinstance(result["topology"].get("devices"), list)
    assert isinstance(result["topology"].get("links"), list)
    assert any("topology" in warning.lower() for warning in result["warnings"])


def test_agent_crash_is_logged_and_remaining_agents_continue(monkeypatch):
    def crash(_records):
        raise RuntimeError("simulated agent crash")

    monkeypatch.setattr(agents, "performance_agent", crash)
    result = agents.run_diagnosis({"records": [one_record({"latency_ms": 180, "jitter_ms": 40})]})
    failed = next(message for message in result["agent_messages"] if message["source_agent"] == "performance_agent")
    assert failed["status"] == "error"
    assert "simulated agent crash" in " ".join(failed["findings"])
    assert any(message["source_agent"] == "infrastructure_agent" for message in result["agent_messages"])
    assert any("performance_agent" in limitation for limitation in result["report"]["limitations"])
    assert result["report"]["confidence"] <= 0.5


def test_invalid_agent_message_is_rejected_not_raised(monkeypatch):
    monkeypatch.setattr(agents, "performance_agent", lambda _records: {"schema_version": "broken"})
    result = agents.run_diagnosis({"records": [one_record({"latency_ms": 180, "jitter_ms": 40})]})
    rejected = next(message for message in result["agent_messages"] if message["source_agent"] == "performance_agent")
    assert rejected["status"] == "error"
    assert "rejected" in " ".join(rejected["findings"]).lower()


@pytest.mark.parametrize("agent_name", ["correlation_agent", "reporting_agent"])
def test_downstream_agent_crash_is_isolated(monkeypatch, agent_name):
    def crash(*_args, **_kwargs):
        raise RuntimeError("downstream crash")

    monkeypatch.setattr(agents, agent_name, crash)
    result = agents.run_diagnosis({"records": [one_record({"latency_ms": 180, "jitter_ms": 45, "packet_loss_pct": 3})]})
    failed = next(message for message in result["agent_messages"] if message["source_agent"] == agent_name)
    assert failed["status"] == "error"
    assert agent_name in " ".join(result["report"]["limitations"])
    assert result["report"]["confidence"] <= 0.5


def test_duplicate_records_do_not_inflate_confidence(demo):
    record = next(row for row in demo["records"] if row["scenario"] == "link_congestion")
    single = agents.run_diagnosis({"records": [record], "topology": demo["topology"]})["report"]
    repeated = agents.run_diagnosis({"records": [record] * 500, "topology": demo["topology"]})["report"]
    assert repeated["confidence"] == single["confidence"]
    assert repeated["ranked_candidates"] == single["ranked_candidates"]


def test_close_top_candidates_are_ambiguous_with_discriminator():
    performance = envelope("performance_agent", [
        ev("latency_ms", 180, "ms"), ev("link_utilization_pct", 75, "%"),
        ev("packet_loss_pct", 8, "%"), ev("signal_strength_dbm", -82, "dBm"),
        ev("retransmissions_pct", 30, "%"),
    ])
    result = agents.run_diagnosis({"records": [one_record({
        "latency_ms": 180, "link_utilization_pct": 75, "packet_loss_pct": 8,
        "signal_strength_dbm": -82, "retransmissions_pct": 30,
    })]})
    report = result["report"]
    assert report["status"] == "ambiguous"
    assert len(report["tied_candidates"]) >= 2
    assert any("discriminat" in action.lower() or "compare" in action.lower() for action in report["recommended_actions"])
    assert report["confidence"] <= 0.5


def test_latency_alone_is_not_congestion_and_wifI_signals_win():
    latency_only = agents.run_diagnosis({"records": [one_record({"latency_ms": 240, "packet_loss_pct": 3, "link_utilization_pct": 20})]})
    assert all(candidate["cause"] != "Link congestion" for candidate in latency_only["ranked_candidates"])

    wifi = agents.run_diagnosis({"records": [one_record({
        "latency_ms": 180, "packet_loss_pct": 8, "link_utilization_pct": 25,
        "signal_strength_dbm": -82, "retransmissions_pct": 31,
    })]})["report"]
    assert wifi["suspected_root_cause"] == "Weak Wi-Fi"


def test_hardware_failure_outranks_congestion_symptoms(demo):
    record = next(row for row in demo["records"] if row["scenario"] == "hardware_failure")
    result = agents.run_diagnosis({"records": [record], "topology": demo["topology"]})["report"]
    assert result["suspected_root_cause"] == "Hardware failure"


def test_single_family_wifi_can_diagnose_with_three_distinct_signals():
    result = agents.run_diagnosis({"records": [one_record({
        "signal_strength_dbm": -84, "retransmissions_pct": 28, "packet_loss_pct": 9,
    })]})["report"]
    assert result["suspected_root_cause"] == "Weak Wi-Fi"
    assert result["confidence"] <= 0.55
    assert "single evidence family" in " ".join(result["limitations"]).lower()


def test_confidence_penalties_are_applied_and_interop_is_lower(demo):
    rows = {row["scenario"]: row for row in demo["records"]}
    clean = agents.run_diagnosis({"records": [rows["link_congestion"]], "topology": demo["topology"]})["report"]
    interop = agents.run_diagnosis({"records": [rows["interoperability_failure"]], "topology": demo["topology"]})["report"]
    assert interop["confidence"] < clean["confidence"]
    penalties = interop["confidence_breakdown"]["penalties"]
    assert penalties["unsupported_schema"] == pytest.approx(0.15)
    assert penalties["ignored_metrics"] >= 0.05
    no_topology = agents.run_diagnosis({"records": [rows["link_congestion"]]})["report"]
    assert no_topology["confidence"] <= clean["confidence"] - 0.09


def test_clear_multi_agent_cases_receive_stronger_confidence_than_single_family(demo):
    rows = {row["scenario"]: row for row in demo["records"]}
    clean = agents.run_diagnosis({"records": [rows["link_congestion"]], "topology": demo["topology"]})["report"]
    wifi = agents.run_diagnosis({"records": [rows["weak_wifi"]], "topology": demo["topology"]})["report"]
    interop = agents.run_diagnosis({"records": [rows["interoperability_failure"]], "topology": demo["topology"]})["report"]
    assert clean["confidence"] >= 0.75
    assert wifi["confidence"] >= 0.40
    assert interop["confidence"] < clean["confidence"] - 0.15


def test_fractional_percent_and_seconds_alias_are_warned_and_ignored():
    result = agents.run_diagnosis({"records": [one_record({
        "link_utilization_pct": 0.94, "cpu_utilization_pct": 0.8,
        "packet_loss_pct": 0.05, "latency": 0.28,
    })]})
    assert "link_utilization_pct" not in result["records"][0]["metrics"]
    assert "cpu_utilization_pct" not in result["records"][0]["metrics"]
    assert "latency_ms" not in result["records"][0]["metrics"]
    text = " ".join(result["warnings"]).lower()
    assert "0-1" in text and "seconds" in text


def test_report_and_each_message_match_schema_and_are_directed(demo):
    result = agents.run_diagnosis({"records": [demo["records"][3]], "topology": demo["topology"]})
    for message in result["agent_messages"]:
        message_schema = {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/agent_message_v1"}
        assert list(Draft202012Validator(message_schema).iter_errors(message)) == []
    assert result["agent_messages"][-2]["target_agent"] == "reporting_agent"
    assert set(result["agent_messages"][-2]["received_message_ids"]) == {m["message_id"] for m in result["agent_messages"][:3]}
    report_schema = {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/diagnostic_report"}
    assert list(Draft202012Validator(report_schema).iter_errors(result["report"])) == []
    assert all(item["source_message_id"] for item in result["report"]["supporting_evidence"])


def test_reporting_agent_receives_correlator_output_as_structured_handoff(demo):
    result = agents.run_diagnosis({"records": [demo["records"][3]], "topology": demo["topology"]})
    reporter = next(message for message in result["agent_messages"] if message["source_agent"] == "reporting_agent")
    correlator = next(message for message in result["agent_messages"] if message["source_agent"] == "correlation_agent")
    assert reporter["target_agent"] == "orchestrator"
    assert correlator["message_id"] in reporter["received_message_ids"]
    assert result["report"]["suspected_root_cause"] in " ".join(reporter["findings"])


def test_mixed_faults_keep_ranked_candidates():
    record = one_record({
        "link_utilization_pct": 94, "queue_drops": 160, "latency_ms": 280,
        "interface_errors": 128,
    })
    result = agents.run_diagnosis({"records": [record], "topology": {"devices": [{"id": "EDGE_1"}], "links": []}})
    causes = [item["cause"] for item in result["report"]["ranked_candidates"]]
    assert "Link congestion" in causes
    assert "Ethernet/interface fault" in causes


def test_conflicts_reduce_confidence_and_are_explained():
    result = agents.run_diagnosis({"records": [one_record({"latency_ms": 180, "jitter_ms": 45, "packet_loss_pct": 3})]})
    assert result["report"]["conflicts"]
    assert all({"agents", "claims", "resolution_rule"} <= conflict.keys() for conflict in result["report"]["conflicts"])


def test_same_input_produces_same_report_except_incident_id(demo):
    payload = {"records": [demo["records"][3]], "topology": demo["topology"]}
    first = agents.run_diagnosis(payload)["report"]
    second = agents.run_diagnosis(payload)["report"]
    first.pop("incident_id")
    second.pop("incident_id")
    assert first == second


def test_beginner_and_expert_views_show_different_telemetry_detail():
    records = [one_record({"latency_ms": 180, "jitter_ms": 40, "queue_drops": 65})]
    beginner = build_telemetry_view(records, "Beginner")
    expert = build_telemetry_view(records, "Expert")
    assert beginner["mode"] == "Beginner"
    assert beginner["rows"][0]["Key observations"]
    assert "latency_ms" not in beginner["columns"]
    assert expert["rows"][0]["latency_ms"] == 180
    assert expert["columns"] != beginner["columns"]


def test_optional_model_reviewer_adds_validated_advisory_without_changing_verdict():
    payload = {"records": [one_record({"link_utilization_pct": 94, "queue_drops": 90, "latency_ms": 180})], "topology": {"devices": [{"id": "EDGE_1"}], "links": []}}
    deterministic = agents.run_diagnosis(payload)
    expected_cause = deterministic["report"]["suspected_root_cause"]
    expected_confidence = deterministic["report"]["confidence"]
    review = {
        "status": "reviewed",
        "agrees_with_rule_verdict": True,
        "summary": "The measurements support the deterministic verdict.",
        "alternative_explanations": [],
        "recommended_checks": ["Compare link queue counters over the same interval."],
        "uncertainty": "Only one device has a usable sample.",
    }
    result = agents.run_diagnosis(payload, model_reviewer=lambda _report, _messages: review)
    assert result["report"]["suspected_root_cause"] == expected_cause
    assert result["report"]["confidence"] == expected_confidence
    assert result["report"]["model_review"] == review
    model_message = next(m for m in result["agent_messages"] if m["source_agent"] == "groq_review_agent")
    assert model_message["target_agent"] == "reporting_agent"
    assert model_message["received_message_ids"]


def test_model_review_failure_preserves_deterministic_report():
    payload = {"records": [one_record({"latency_ms": 180, "jitter_ms": 40})]}

    def fail(_report, _messages):
        raise RuntimeError("provider unavailable")

    result = agents.run_diagnosis(payload, model_reviewer=fail)
    assert result["report"]["model_review"]["status"] == "unavailable"
    assert result["report"]["suspected_root_cause"] == "Latency spike"
    assert any("model review failed" in note.lower() for note in result["report"]["limitations"])


def test_groq_reviewer_requests_schema_bound_advisory_without_live_network(demo):
    report = agents.run_diagnosis({"records": [demo["records"][3]], "topology": demo["topology"]})["report"]
    content = json.dumps({
        "status": "reviewed", "agrees_with_rule_verdict": True,
        "summary": "The candidate matches the measurements.", "alternative_explanations": [],
        "recommended_checks": ["Compare queue counters."], "uncertainty": "One scenario sample.",
    })

    class FakeCompletions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]})()

    completions = FakeCompletions()
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    review = review_diagnosis(report, [], "test-key", client=client)
    assert review["status"] == "reviewed"
    assert completions.kwargs["model"] == GROQ_MODEL
    assert completions.kwargs["response_format"]["json_schema"]["strict"] is True
    assert "records" not in completions.kwargs["messages"][1]["content"]

