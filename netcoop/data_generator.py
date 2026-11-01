"""Deterministic synthetic telemetry based on the linked Colab notebook."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
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


def generate_fuzz_case(rng: random.Random) -> tuple[dict, str]:
    """Randomized accuracy/fuzz input: overlapping faults, jitter, and omissions."""
    labels=["normal","Link congestion","Weak Wi-Fi","Hardware failure","Ethernet/interface fault","DNS/DHCP service failure"]
    chosen=rng.choice(labels)
    base={"cpu_utilization_pct":rng.uniform(15,55),"link_utilization_pct":rng.uniform(25,60),"packet_loss_pct":rng.uniform(0,.8),"latency_ms":rng.uniform(8,70),"jitter_ms":rng.uniform(1,15),"queue_drops":rng.randint(0,20)}
    def add_fault(fault):
        if fault=="Link congestion": base.update(link_utilization_pct=rng.uniform(76,100),queue_drops=rng.randint(60,900),latency_ms=rng.uniform(105,500),packet_loss_pct=rng.uniform(2.2,15))
        elif fault=="Weak Wi-Fi": base.update(signal_strength_dbm=rng.uniform(-92,-76),retransmissions_pct=rng.uniform(17,60),packet_loss_pct=rng.uniform(2,15))
        elif fault=="Hardware failure": base.update(cpu_utilization_pct=rng.uniform(88,100),interface_errors=rng.randint(20,600))
        elif fault=="Ethernet/interface fault": base.update(interface_errors=rng.randint(30,800),packet_loss_pct=rng.uniform(2,10))
        elif fault=="DNS/DHCP service failure": base.update(service_status=0)
    if chosen=="DNS/DHCP service failure": base={"latency_ms":rng.uniform(3,50)}
    if chosen!="normal": add_fault(chosen)
    # Add a distinct second fault to 20% of cases. A nominal baseline with a
    # superimposed fault is labeled by that fault, never as normal operation.
    if rng.random()<.20:
        second=rng.choice([label for label in labels if label not in {"normal",chosen}])
        add_fault(second)
        if chosen=="normal": chosen=second
    if base and rng.random()<.08: base.pop(rng.choice(list(base)))
    status="Healthy" if chosen=="normal" else "Warning"
    if chosen=="Hardware failure": status="Critical"
    return ({"device_id":f"FUZZ_{rng.randrange(20)}","device_type":"service" if chosen=="DNS/DHCP service failure" else rng.choice(["switch","router","access_point"]),"site":"fuzz segment","timestamp":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":status,"metrics":base},chosen)


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
    return {"dataset_version": "1.0", "seed": seed, "fixture": True, "topology": topology, "records": records}


def build_demo_timeseries(seed: int = SEED, samples_per_scenario: int = 12, interval_minutes: int = 4) -> dict:
    """Build a labelled short time series for dashboard charts.

    Seven usable scenarios have twelve jittered readings each by default. The two input-
    quality demonstrations remain single records so their malformed values do
    not swamp the timeline. This is synthetic history, not measured traffic.
    """
    if samples_per_scenario < 2 or interval_minutes < 1:
        raise ValueError("Use at least two samples and a positive interval.")
    base = build_demo_data(seed)
    rng = random.Random(seed + 1)
    series_names = [name for name in SCENARIOS if name not in {"interoperability_failure", "malformed_input"}]
    latest = datetime.now(timezone.utc)
    records = []
    fixed_devices = {
        "normal": "SW_CAMPUS_10", "latency_spike": "SW_CAMPUS_10",
        "hardware_failure": "HOSTEL_CORE_SW_01",
    }
    fixed_sites = {"normal": "Campus", "latency_spike": "Campus", "hardware_failure": "Hostel network"}
    for name in series_names:
        template = next(row for row in base["records"] if row["scenario"] == name)
        for index in range(samples_per_scenario):
            row = generate_scenario(name, rng)
            row.update({key: template[key] for key in ("device_id", "device_type", "site")})
            row["device_id"] = fixed_devices.get(name, row["device_id"])
            row["site"] = fixed_sites.get(name, row["site"])
            metrics = row["metrics"]
            if name == "link_congestion":
                metrics.update(link_utilization_pct=round(rng.uniform(88, 99), 1), queue_drops=rng.randint(100, 300),
                               latency_ms=round(rng.uniform(180, 360), 1), packet_loss_pct=round(rng.uniform(2.5, 5.5), 2),
                               jitter_ms=round(rng.uniform(25, 60), 1))
            elif name == "weak_wifi":
                metrics.update(signal_strength_dbm=round(rng.uniform(-89, -76), 1), retransmissions_pct=round(rng.uniform(18, 40), 1),
                               packet_loss_pct=round(rng.uniform(3, 12), 2), latency_ms=round(rng.uniform(130, 240), 1))
            elif name == "interface_fault":
                metrics.update(interface_errors=rng.randint(80, 220), packet_loss_pct=round(rng.uniform(2, 8), 2),
                               latency_ms=round(rng.uniform(60, 130), 1))
            elif name == "dns_dhcp_failure":
                metrics.update(service_status=0, latency_ms=round(rng.uniform(3, 20), 1), packet_loss_pct=0.0)
            timestamp = latest - timedelta(minutes=(samples_per_scenario - index - 1) * interval_minutes)
            row["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
            records.append(row)
    # Keep deliberately malformed and incompatible examples separate from the
    # trend histories; they are useful for input handling, not charting.
    for name in ("interoperability_failure", "malformed_input"):
        row = next(row for row in base["records"] if row["scenario"] == name)
        row["timestamp"] = latest.isoformat().replace("+00:00", "Z")
        records.append(row)
    return {"dataset_version": "1.1", "seed": seed, "fixture": True, "topology": base["topology"], "records": records,
            "synthetic_history": {"samples_per_scenario": samples_per_scenario, "interval_minutes": interval_minutes,
                                  "series_scenarios": series_names}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/sample_telemetry.json")
    parser.add_argument("--timeseries", action="store_true", help="write chart-ready synthetic histories instead of one record per scenario")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = build_demo_timeseries() if args.timeseries else build_demo_data()
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
