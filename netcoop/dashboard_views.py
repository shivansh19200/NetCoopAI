"""Presentation helpers for beginner and expert telemetry views."""
from __future__ import annotations


def build_telemetry_view(records: list[dict], mode: str) -> dict:
    """Return a plain-language snapshot or the full metric table for the dashboard."""
    if mode == "Expert":
        metric_names = sorted({key for record in records for key in record.get("metrics", {})})
        columns = ["Device", "Type", "Status", *metric_names]
        rows = [
            {"Device": record["device_id"], "Type": record["device_type"], "Status": record["status"], **record.get("metrics", {})}
            for record in records
        ]
        return {"mode": "Expert", "columns": columns, "rows": rows}

    rows = []
    for record in records:
        metrics = record.get("metrics", {})
        observations = []
        for name, value in metrics.items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if name == "latency_ms" and value >= 100:
                observations.append(f"Slow response ({value:g} ms)")
            elif name == "jitter_ms" and value >= 30:
                observations.append(f"Uneven response time ({value:g} ms jitter)")
            elif name == "packet_loss_pct" and value >= 2:
                observations.append(f"Some data is being lost ({value:g}%)")
            elif name == "link_utilization_pct" and value >= 70:
                observations.append(f"Link is {value:g}% full (normal is under 70%)")
            elif name == "cpu_utilization_pct" and value > 85:
                observations.append(f"Device processor is busy ({value:g}%)")
            elif name == "queue_drops" and value > 50:
                observations.append(f"Device dropped {value:g} packets waiting in a queue")
            elif name == "signal_strength_dbm" and value <= -75:
                observations.append(f"Wi-Fi signal is weak ({value:g} dBm)")
            elif name == "retransmissions_pct" and value > 15:
                observations.append(f"Wi-Fi had to resend {value:g}% of packets")
            elif name == "interface_errors" and value > 10:
                observations.append(f"Network port counted {value:g} errors")
        rows.append({
            "Device": record.get("device_id", "Unknown device"),
            "Status": record.get("status", "Unknown"),
            "Key observations": "; ".join(observations) if observations else "No key warning-level readings in the available measurements",
        })
    return {"mode": "Beginner", "columns": ["Device", "Status", "Key observations"], "rows": rows}
