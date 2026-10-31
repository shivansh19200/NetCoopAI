"""Deterministic synthetic telemetry based on the linked Colab notebook."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

SEED = 20261031


def generate_telemetry(fault_type: str = "normal", rng: random.Random | None = None) -> dict:
    """Generate one device record using the Colab baseline and extensions."""
    rng = rng or random.Random()
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "device_id": f"SW_CAMPUS_{rng.randint(1, 10)}",
        "device_type": "switch",
        "site": "Campus core",
        "metrics": {},
    }

    if fault_type == "latency_spike":
        data["metrics"] = {
            "cpu_utilization_pct": round(rng.uniform(40, 70), 2),
            "link_utilization_pct": round(rng.uniform(60, 85), 2),
            "packet_loss_pct": round(rng.uniform(0.1, 1.5), 2),
            "latency_ms": round(rng.uniform(150, 400), 2),
            "jitter_ms": round(rng.uniform(30, 80), 2),
            "queue_drops": rng.randint(0, 50),
        }
        data["status"] = "Warning"
    elif fault_type == "hardware_failure":
        data["metrics"] = {
            "cpu_utilization_pct": 99.9,
            "link_utilization_pct": 100.0,
            "packet_loss_pct": round(rng.uniform(15, 30), 2),
            "latency_ms": round(rng.uniform(500, 1000), 2),
            "queue_drops": rng.randint(5000, 15000),
            "interface_errors": rng.randint(100, 500),
        }
        data["status"] = "Critical"
    else:
        data["metrics"] = {
            "cpu_utilization_pct": round(rng.uniform(10, 35), 2),
            "link_utilization_pct": round(rng.uniform(20, 50), 2),
            "packet_loss_pct": 0.0,
            "latency_ms": round(rng.uniform(5, 20), 2),
            "jitter_ms": round(rng.uniform(1, 5), 2),
            "queue_drops": 0,
        }
        data["status"] = "Healthy"

    return data


def generate_scenario(name: str, rng: random.Random) -> dict:
    """Extend the Colab baseline for the scenarios suggested in the PDF."""
    if name in {"normal", "latency_spike", "hardware_failure"}:
        record = generate_telemetry(name, rng)
        if name == "latency_spike":
            record["metrics"]["link_utilization_pct"] = 58.0
            record["metrics"]["packet_loss_pct"] = 3.4
    elif name == "link_congestion":
        record = generate_telemetry("normal", rng)
        record["device_id"], record["device_type"], record["site"] = "HOSTEL_CORE_SW_01", "switch", "Hostel network"
        record["metrics"].update(link_utilization_pct=94.0, queue_drops=160, latency_ms=280.0, packet_loss_pct=3.2, jitter_ms=42.0)
        record["status"] = "Critical"
    elif name == "weak_wifi":
        record = generate_telemetry("normal", rng)
        record["device_id"], record["device_type"], record["site"] = "HOSTEL_AP_07", "access_point", "Hostel Wi-Fi"
        record["metrics"].update(signal_strength_dbm=-82.0, retransmissions_pct=31.0, packet_loss_pct=8.5, latency_ms=180.0)
        record["status"] = "Warning"
    elif name == "interface_fault":
        record = generate_telemetry("normal", rng)
        record["device_id"], record["device_type"], record["site"] = "DEPT_EDGE_SW_02", "switch", "Engineering department"
        record["metrics"].update(interface_errors=128, packet_loss_pct=6.0, latency_ms=95.0)
        record["status"] = "Warning"
    elif name == "dns_dhcp_failure":
        record = generate_telemetry("normal", rng)
        record["device_id"], record["device_type"], record["site"] = "CAMPUS_DNS_01", "service", "Campus services"
        record["metrics"] = {"service_status": 0, "latency_ms": 8.0, "packet_loss_pct": 0.0}
        record["status"] = "Warning"
        record["service"] = "DNS"
    elif name == "interoperability_failure":
        record = generate_scenario("link_congestion", rng)
        record["schema_version"] = "telemetry_v9"
        record["metrics"]["latency"] = record["metrics"].pop("latency_ms")
        record["units"] = {"latency": "seconds"}
        record["metrics"]["latency"] = 0.28
    elif name == "malformed_input":
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "device_id": "BROKEN_NODE", "metrics": {"latency_ms": "fast", "packet_loss_pct": 400}, "status": "unknown"}
    else:
        raise ValueError(f"Unknown scenario: {name}")
    record["scenario"] = name
    return record


SCENARIOS = [
    "normal", "latency_spike", "hardware_failure", "link_congestion",
    "weak_wifi", "interface_fault", "dns_dhcp_failure",
    "interoperability_failure", "malformed_input",
]


def build_demo_data(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    records = [generate_scenario(name, rng) for name in SCENARIOS]
    topology = {
        "devices": [
            {"id": "INET_GW_01", "label": "Internet gateway", "type": "gateway", "site": "Edge"},
            {"id": "CAMPUS_CORE_01", "label": "Campus core", "type": "router", "site": "Core"},
            {"id": "HOSTEL_CORE_SW_01", "label": "Hostel core switch", "type": "switch", "site": "Hostel"},
            {"id": "HOSTEL_AP_07", "label": "Hostel AP 07", "type": "access_point", "site": "Hostel"},
            {"id": "SW_CAMPUS_10", "label": "Campus edge switch 10", "type": "switch", "site": "Campus"},
            {"id": "DEPT_EDGE_SW_02", "label": "Department edge", "type": "switch", "site": "Department"},
            {"id": "CAMPUS_DNS_01", "label": "DNS / DHCP", "type": "service", "site": "Services"},
        ],
        "links": [
            {"source": "INET_GW_01", "target": "CAMPUS_CORE_01", "utilization_pct": 55},
            {"source": "CAMPUS_CORE_01", "target": "HOSTEL_CORE_SW_01", "utilization_pct": 62},
            {"source": "HOSTEL_CORE_SW_01", "target": "HOSTEL_AP_07", "utilization_pct": 68},
            {"source": "CAMPUS_CORE_01", "target": "SW_CAMPUS_10", "utilization_pct": 48},
            {"source": "CAMPUS_CORE_01", "target": "DEPT_EDGE_SW_02", "utilization_pct": 42},
            {"source": "CAMPUS_CORE_01", "target": "CAMPUS_DNS_01", "utilization_pct": 18},
        ],
    }
    return {"dataset_version": "1.0", "seed": seed, "topology": topology, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/sample_telemetry.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_demo_data(), indent=2), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
