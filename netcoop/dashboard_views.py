"""Presentation helpers for beginner and expert telemetry views."""
from __future__ import annotations


def _range(values: list[float], unit: str = "") -> str:
    low, high = min(values), max(values)
    if low == high:
        return f"{low:g}{unit}"
    return f"{low:g}–{high:g}{unit}"


def build_telemetry_view(records: list[dict], mode: str) -> dict:
    """Return a compact device summary or the full per-reading metric table."""
    if mode == "Expert":
        metric_names = sorted({key for record in records for key in record.get("metrics", {})})
        columns = ["Device", "Type", "Status", *metric_names]
        rows = [
            {"Device": record["device_id"], "Type": record["device_type"], "Status": record["status"], **record.get("metrics", {})}
            for record in records
        ]
        return {"mode": "Expert", "columns": columns, "rows": rows}

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
            "Device": device,
            "Status": latest.get("status", "Unknown"),
            "Readings": len(samples),
            "Key observations": "; ".join(observations[:4]) if observations else "No readings crossed alert thresholds",
        })
    return {"mode": "Beginner", "columns": ["Device", "Status", "Readings", "Key observations"], "rows": rows}
