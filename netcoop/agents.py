"""Small, interoperable rule-based agents for the NetCoop AI demo."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

PROTOCOL = "agent_message_v1"
ALIASES = {
    "latency": "latency_ms", "latency_ms": "latency_ms",
    "jitter": "jitter_ms", "jitter_ms": "jitter_ms",
    "packet_loss": "packet_loss_pct", "packet_loss_pct": "packet_loss_pct",
    "link_utilization": "link_utilization_pct", "link_utilization_pct": "link_utilization_pct",
    "cpu_utilization": "cpu_utilization_pct", "cpu_utilization_pct": "cpu_utilization_pct",
    "memory_utilization": "memory_utilization_pct", "memory_utilization_pct": "memory_utilization_pct",
    "queue_drops": "queue_drops", "interface_errors": "interface_errors",
    "throughput_mbps": "throughput_mbps", "bandwidth_mbps": "bandwidth_mbps",
    "signal_strength_dbm": "signal_strength_dbm", "retransmissions_pct": "retransmissions_pct",
    "service_status": "service_status",
}
UNITS = {
    "latency_ms": "ms", "jitter_ms": "ms", "packet_loss_pct": "%",
    "link_utilization_pct": "%", "cpu_utilization_pct": "%", "memory_utilization_pct": "%",
    "queue_drops": "count", "interface_errors": "count", "throughput_mbps": "Mbps",
    "bandwidth_mbps": "Mbps", "signal_strength_dbm": "dBm", "retransmissions_pct": "%",
    "service_status": "state",
}


def _envelope(source: str, findings: list[str], evidence: list[dict], limitations: list[str], status: str = "ok") -> dict:
    return {
        "schema_version": PROTOCOL,
        "message_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_agent": source,
        "target_agent": "orchestrator",
        "status": status,
        "findings": findings,
        "evidence": evidence,
        "limitations": limitations,
    }


def normalize_records(payload: Any) -> tuple[list[dict], list[str], dict]:
    """Validate supported JSON/CSV payloads; absent values remain absent."""
    warnings: list[str] = []
    if isinstance(payload, list):
        records, topology = payload, {}
    elif isinstance(payload, dict):
        records = payload.get("records", [payload] if "device_id" in payload else [])
        topology = payload.get("topology", {})
        if payload.get("schema_version") not in (None, "telemetry_v1", "telemetry_v2"):
            warnings.append(f"Unsupported telemetry schema version: {payload.get('schema_version')}")
    else:
        return [], ["Input must be a JSON object or array of device records."], {}
    if not isinstance(records, list) or not records:
        return [], warnings + ["No telemetry records were found."], topology

    normalized = []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            warnings.append(f"Record {index + 1} is not an object and was skipped.")
            continue
        metrics = row.get("metrics", {})
        if not isinstance(metrics, dict):
            warnings.append(f"Record {index + 1}: metrics must be an object; record skipped.")
            continue
        cleaned = {}
        row_schema = row.get("schema_version")
        if row_schema not in (None, "telemetry_v1", "telemetry_v2"):
            warnings.append(f"Record {index + 1}: unsupported telemetry schema version `{row_schema}`.")
        units = row.get("units", {}) if isinstance(row.get("units", {}), dict) else {}
        for field, value in metrics.items():
            canonical = ALIASES.get(str(field).lower())
            if not canonical:
                warnings.append(f"Record {index + 1}: unknown metric `{field}` ignored.")
                continue
            expected = UNITS[canonical]
            given = units.get(field)
            if given and given != expected:
                warnings.append(f"Record {index + 1}: `{field}` unit `{given}` is incompatible; expected `{expected}`. Value ignored.")
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                warnings.append(f"Record {index + 1}: `{field}` is not numeric; value ignored.")
                continue
            bounds = {
                "latency_ms": (0, 60000), "jitter_ms": (0, 60000), "packet_loss_pct": (0, 100),
                "link_utilization_pct": (0, 100), "cpu_utilization_pct": (0, 100),
                "memory_utilization_pct": (0, 100), "queue_drops": (0, 1e12),
                "interface_errors": (0, 1e12), "throughput_mbps": (0, 1e9),
                "bandwidth_mbps": (0, 1e9), "signal_strength_dbm": (-120, 0),
                "retransmissions_pct": (0, 100), "service_status": (0, 1),
            }[canonical]
            if not bounds[0] <= number <= bounds[1]:
                warnings.append(f"Record {index + 1}: `{field}` value {value!r} is outside the accepted range; value ignored.")
                continue
            cleaned[canonical] = number
        normalized.append({
            "device_id": str(row.get("device_id") or f"UNKNOWN_{index + 1}"),
            "device_type": str(row.get("device_type", "device")),
            "site": str(row.get("site", "Unknown site")),
            "status": str(row.get("status", "Unknown")),
            "service": row.get("service"),
            "scenario": row.get("scenario", "uploaded data"),
            "metrics": cleaned,
        })
    return normalized, warnings, topology


def _evidence(row: dict, metric: str, interpretation: str) -> dict:
    return {"device_id": row["device_id"], "metric": metric, "value": row["metrics"][metric], "unit": UNITS[metric], "interpretation": interpretation}


def performance_agent(records: list[dict]) -> dict:
    findings, evidence = [], []
    for row in records:
        m = row["metrics"]
        signals = [
            ("latency_ms", 100, "Elevated latency"), ("jitter_ms", 30, "Elevated jitter"),
            ("packet_loss_pct", 2, "Packet loss above 2%"), ("link_utilization_pct", 85, "High link utilization"),
            ("retransmissions_pct", 15, "High wireless retransmissions"),
        ]
        for metric, threshold, description in signals:
            if metric in m and m[metric] >= threshold:
                evidence.append(_evidence(row, metric, description))
        if "signal_strength_dbm" in m and m["signal_strength_dbm"] <= -75:
            evidence.append(_evidence(row, "signal_strength_dbm", "Weak Wi-Fi signal"))
    if evidence:
        findings.append(f"Performance agent found {len(evidence)} above-threshold measurement(s).")
    else:
        findings.append("No above-threshold performance readings were observed in the available metrics.")
    return _envelope("performance_agent", findings, evidence, [])


def infrastructure_agent(records: list[dict]) -> dict:
    evidence = []
    for row in records:
        m = row["metrics"]
        for metric, threshold, text in [
            ("cpu_utilization_pct", 85, "High device CPU utilization"),
            ("memory_utilization_pct", 90, "High device memory utilization"),
            ("queue_drops", 50, "Elevated egress queue drops"),
            ("interface_errors", 10, "Elevated interface errors"),
        ]:
            if metric in m and m[metric] > threshold:
                evidence.append(_evidence(row, metric, text))
        if row["status"].lower() in {"critical", "down", "failed"}:
            evidence.append({"device_id": row["device_id"], "metric": "device_status", "value": row["status"], "unit": "state", "interpretation": "Device reports critical or failed status"})
    findings = [f"Infrastructure agent found {len(evidence)} health concern(s)." if evidence else "No infrastructure thresholds were exceeded in available metrics."]
    return _envelope("infrastructure_agent", findings, evidence, [])


def connectivity_agent(records: list[dict], topology: dict) -> dict:
    evidence = []
    topology_ids = {str(d.get("id")) for d in topology.get("devices", []) if isinstance(d, dict)}
    for row in records:
        if row["device_id"] in topology_ids:
            evidence.append({"device_id": row["device_id"], "metric": "topology_scope", "value": row["site"], "unit": "topology", "interpretation": "Telemetry device maps to a known topology segment"})
    if topology.get("links"):
        for link in topology["links"]:
            value = link.get("utilization_pct")
            if isinstance(value, (float, int)) and value >= 85:
                evidence.append({"device_id": f"{link.get('source')} → {link.get('target')}", "metric": "link_utilization_pct", "value": value, "unit": "%", "interpretation": "Topology link is highly utilized"})
    services = [r for r in records if "service_status" in r["metrics"] and r["metrics"]["service_status"] < 1]
    for row in services:
        evidence.append(_evidence(row, "service_status", f"{row.get('service') or 'Network service'} is unavailable"))
    findings = [f"Connectivity agent mapped {len(evidence)} topology/service concern(s)." if evidence else "No affected link or service scope could be inferred from the supplied topology and records."]
    limitations = [] if topology else ["No topology was supplied; affected segments cannot be inferred."]
    return _envelope("connectivity_agent", findings, evidence, limitations)


def correlation_agent(messages: list[dict]) -> dict:
    by_agent = {m["source_agent"]: m for m in messages}
    evidence = [e for m in messages if m["source_agent"] in {"performance_agent", "infrastructure_agent", "connectivity_agent"} for e in m["evidence"]]
    scope_devices = {e["device_id"] for e in evidence if e["metric"] == "topology_scope"}
    candidates: dict[str, dict] = {}

    def add(cause: str, family: str, item: dict, corroboration: bool = False) -> None:
        c = candidates.setdefault(cause, {"families": set(), "evidence": [], "corroboration": 0})
        c["families"].add(family)
        c["evidence"].append(item)
        c["corroboration"] += int(corroboration)

    for item in evidence:
        metric, value = item["metric"], item["value"]
        if metric == "topology_scope":
            continue
        fam = "performance_agent" if metric in {"latency_ms", "jitter_ms", "packet_loss_pct", "link_utilization_pct", "signal_strength_dbm", "retransmissions_pct"} else ("connectivity_agent" if metric == "service_status" else "infrastructure_agent")
        if metric == "service_status": add("DNS/DHCP service failure", fam, item)
        if metric in {"link_utilization_pct", "queue_drops", "latency_ms"} and ((metric == "link_utilization_pct" and value >= 85) or (metric == "queue_drops" and value > 50) or (metric == "latency_ms" and value >= 100)):
            add("Link congestion", fam, item, metric in {"queue_drops", "latency_ms"})
        if metric in {"signal_strength_dbm", "retransmissions_pct"}:
            add("Weak Wi-Fi signal", fam, item, metric == "retransmissions_pct")
        if metric == "interface_errors": add("Ethernet/interface fault", fam, item)
        if metric in {"cpu_utilization_pct", "memory_utilization_pct"} and value >= 85: add("Device resource saturation", fam, item)
        if metric == "device_status" and str(value).lower() in {"critical", "failed", "down"}: add("Hardware/device failure", fam, item)
        # The connectivity specialist independently confirms the affected segment.
        # This adds scope context without inventing another metric measurement.
        if item["device_id"] in scope_devices:
            scoped = {"device_id": item["device_id"], "metric": "topology_scope", "value": "mapped", "unit": "topology", "interpretation": "Affected device is present in network topology"}
            for candidate_name in list(candidates):
                if any(e["device_id"] == item["device_id"] for e in candidates[candidate_name]["evidence"]):
                    add(candidate_name, "connectivity_agent", scoped)
    # A critical device with saturated CPU and substantial interface errors is
    # stronger hardware evidence than congestion symptoms alone. Corroborate it
    # with its own loss/latency readings when those signals are present.
    for message in messages:
        if message["source_agent"] != "infrastructure_agent":
            continue
        for item in message["evidence"]:
            if item["metric"] != "device_status" or str(item["value"]).lower() not in {"critical", "failed", "down"}:
                continue
            device = item["device_id"]
            device_evidence = [e for e in evidence if e["device_id"] == device]
            has_extreme_cpu = any(e["metric"] == "cpu_utilization_pct" and e["value"] >= 95 for e in device_evidence)
            has_errors = any(e["metric"] == "interface_errors" and e["value"] >= 50 for e in device_evidence)
            if has_extreme_cpu and has_errors:
                add("Hardware/device failure", "infrastructure_agent", item)
                for signal in device_evidence:
                    if signal["metric"] in {"latency_ms", "packet_loss_pct"}:
                        add("Hardware/device failure", "performance_agent", signal, True)
                if device in scope_devices:
                    add("Hardware/device failure", "connectivity_agent", {"device_id": device, "metric": "topology_scope", "value": "mapped", "unit": "topology", "interpretation": "Affected device is present in network topology"})
    ranked = []
    for cause, candidate in candidates.items():
        score = min(0.95, 0.30 * len(candidate["families"]) + min(0.10, 0.025 * candidate["corroboration"]))
        ranked.append({"cause": cause, "score": round(score, 2), "families": sorted(candidate["families"]), "evidence": candidate["evidence"]})
    ranked.sort(key=lambda c: (c["score"], len(c["evidence"])), reverse=True)
    winner = ranked[0] if ranked else None
    enough = bool(winner and winner["score"] >= 0.42 and len(winner["families"]) >= 2)
    findings = [f"Ranked {len(ranked)} candidate cause(s) using independent evidence families." if ranked else "No cause-specific evidence met a rule threshold."]
    if winner and not enough:
        findings.append("Evidence did not meet the two-family, 0.42 score threshold; no definitive cause is reported.")
    return {
        "message": _envelope("correlation_agent", findings, winner["evidence"] if winner else [], ["Evidence score is rule-based, not calibrated probability."] if ranked else ["No above-threshold evidence is available."], "ok" if enough else "warning"),
        "ranked_candidates": ranked,
        "winner": winner if enough else None,
    }


def reporting_agent(correlation: dict, records: list[dict], warnings: list[str], messages: list[dict]) -> tuple[dict, dict]:
    winner = correlation["winner"]
    cause = winner["cause"] if winner else "Insufficient evidence to identify a probable root cause"
    action_map = {
        "Link congestion": ["Inspect the affected link and upstream utilization over the incident window.", "Review queue policy and traffic distribution before making changes."],
        "Weak Wi-Fi signal": ["Check AP placement, channel contention, and client signal quality.", "Compare retransmission rates across nearby access points."],
        "Ethernet/interface fault": ["Inspect interface counters, cabling, optics, and link flaps.", "Compare error deltas on both ends of the affected link."],
        "DNS/DHCP service failure": ["Check DNS/DHCP service health and recent configuration changes.", "Verify client resolution or lease acquisition from an affected segment."],
        "Device resource saturation": ["Review CPU and memory trends alongside device process health.", "Check whether load is localized to one device or shared upstream."],
        "Hardware/device failure": ["Verify device alarms, power, and interface state with an operator.", "Compare neighboring devices before isolating the suspected component."],
    }
    devices = sorted({r["device_id"] for r in records if winner and any(e["device_id"] == r["device_id"] for e in winner["evidence"])})
    report = {
        "incident_id": f"INC-{uuid.uuid4().hex[:8].upper()}",
        "status": "diagnosed" if winner else "insufficient_evidence",
        "suspected_root_cause": cause,
        "confidence": winner["score"] if winner else 0.0,
        "affected_devices": devices,
        "supporting_evidence": [{k: e[k] for k in ("metric", "value", "unit", "interpretation", "device_id")} for e in (winner["evidence"] if winner else [])],
        "alternative_causes": [c["cause"] for c in correlation["ranked_candidates"] if winner and c["cause"] != cause][:3],
        "recommended_actions": action_map.get(cause, ["Collect a time-aligned sample of latency, loss, device health, and topology data.", "Compare affected and unaffected devices before escalating a root-cause claim."]),
        "evidence_sources": winner["families"] if winner else sorted({m["source_agent"] for m in messages}),
        "limitations": list(dict.fromkeys([*warnings, *(m["limitations"][0] for m in messages if m["limitations"]), "Confidence is an evidence score, not a calibrated probability."])),
    }
    msg = _envelope("reporting_agent", [f"Produced {report['status']} report {report['incident_id']}."], report["supporting_evidence"], report["limitations"])
    return report, msg


def run_diagnosis(payload: Any) -> dict:
    records, warnings, topology = normalize_records(payload)
    messages = [performance_agent(records), infrastructure_agent(records), connectivity_agent(records, topology)]
    corr = correlation_agent(messages)
    messages.append(corr["message"])
    report, report_message = reporting_agent(corr, records, warnings, messages)
    messages.append(report_message)
    return {"records": records, "topology": topology, "warnings": warnings, "agent_messages": messages, "ranked_candidates": corr["ranked_candidates"], "report": report, "messages_json": json.dumps(messages, indent=2)}
