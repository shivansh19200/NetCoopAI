"""Presentation helpers for beginner and expert telemetry views."""
from __future__ import annotations


def _range(values: list[float], unit: str = "") -> str:
    low, high = min(values), max(values)
    if low == high:
        return f"{low:g}{unit}"
    return f"{low:g}–{high:g}{unit}"


def distinct_problem_count(report: dict) -> int:
    """Count unique device and metric pairs in the report evidence."""
    return len({(item.get("device_id"), item.get("metric"))
                for item in report.get("supporting_evidence", [])
                if item.get("metric") != "topology_scope"})


def warning_summary(warnings: list[str]) -> str:
    """Turn detailed parser warnings into a short operator-friendly line."""
    duplicate_count = 0
    ignored_count = 0
    stale_hours = 0
    for warning in warnings:
        if "duplicate record" in warning.lower():
            import re
            match = re.search(r"(\d+) duplicate", warning)
            duplicate_count += int(match.group(1)) if match else 0
        elif any(token in warning.lower() for token in ("ignored", "is incompatible", "is not numeric")):
            ignored_count += 1
        if "stale" in warning.lower():
            import re
            match = re.search(r"\(([\d.]+) hours old\)", warning)
            stale_hours = max(stale_hours, round(float(match.group(1)))) if match else stale_hours
    parts = []
    if duplicate_count:
        parts.append(f"{duplicate_count} duplicate reading{'s' if duplicate_count != 1 else ''} ignored")
    if ignored_count:
        parts.append(f"{ignored_count} reading field{'s' if ignored_count != 1 else ''} ignored")
    if stale_hours:
        parts.append(f"data about {stale_hours} hours old")
    return "; ".join(parts) or ("Some input details need review" if warnings else "No input issues found")


def confidence_explanation(report: dict) -> str:
    """Explain confidence without exposing the scoring formula."""
    if report.get("status") == "healthy":
        return "Several normal readings support this result."
    penalties = report.get("confidence_breakdown", {}).get("penalties", {})
    if any(penalties.get(key, 0) for key in ("stale_telemetry", "ignored_metrics", "unsupported_schema")):
        return "Some readings were old, missing, or could not be used."
    if report.get("confidence", 0) < .45:
        return "The available readings do not strongly separate the possible causes."
    return "Several useful readings point to this cause."


def build_telemetry_view(records: list[dict], mode: str, devices: list[dict] | None = None) -> dict:
    """Return a compact device summary or the full per-reading metric table."""
    if mode == "Expert":
        metric_names = sorted({key for record in records for key in record.get("metrics", {})})
        columns = ["Device", "Type", "Status", *metric_names]
        rows = [
            {"Device": record["device_id"], "Type": record["device_type"], "Status": record["status"], **record.get("metrics", {})}
            for record in records
        ]
        return {"mode": "Expert", "columns": columns, "rows": rows}

    labels = {str(device.get("id")): str(device.get("label")) for device in (devices or []) if device.get("id")}
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(str(record.get("device_id", "Unknown device")), []).append(record)

    thresholds = [
        ("link_utilization_pct", "Link use", "%", lambda value: value >= 70, "above 70%"),
        ("packet_loss_pct", "Packet loss", "%", lambda value: value >= 2, "above 2%"),
        ("latency_ms", "Latency", " ms", lambda value: value >= 100, "above 100 ms"),
        ("cpu_utilization_pct", "CPU use", "%", lambda value: value > 85, "above 85%"),
        ("queue_drops", "Queue drops", "", lambda value: value > 50, "above 50"),
        ("signal_strength_dbm", "Wi-Fi signal", " dBm", lambda value: value <= -75, "weak at or below -75 dBm"),
        ("retransmissions_pct", "Wi-Fi retries", "%", lambda value: value > 15, "above 15%"),
        ("interface_errors", "Port errors", "", lambda value: value > 10, "above 10"),
    ]
    rows = []
    for device, samples in grouped.items():
        observations = []
        for metric, label, unit, is_alert, threshold_note in thresholds:
            values = [float(sample.get("metrics", {}).get(metric)) for sample in samples
                      if isinstance(sample.get("metrics", {}).get(metric), (int, float))]
            if values and any(is_alert(value) for value in values):
                observations.append(f"{label} {_range(values, unit)} ({threshold_note})")
        latest = max(samples, key=lambda row: str(row.get("timestamp", "")))
        rows.append({
            "Device": labels.get(device, device.replace("_", " ").title()),
            "Status": {"critical": "Needs attention", "warning": "Check readings", "healthy": "OK", "down": "Unreachable"}.get(str(latest.get("status", "Unknown")).lower(), latest.get("status", "Unknown")),
            "Readings": len(samples),
            "Key observations": "; ".join(observations[:4]) if observations else "No readings crossed alert thresholds",
        })
    return {"mode": "Beginner", "columns": ["Device", "Status", "Readings", "Key observations"], "rows": rows}
