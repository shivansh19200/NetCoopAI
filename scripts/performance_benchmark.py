"""Measure diagnosis latency and traced Python memory at increasing record counts."""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
import tracemalloc
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netcoop.agents import run_diagnosis  # noqa: E402
from netcoop.data_generator import build_demo_timeseries  # noqa: E402


def payload_for_size(size: int) -> dict:
    history = build_demo_timeseries()
    template = next(r for r in history["records"] if r.get("scenario") == "link_congestion")
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(size):
        row = deepcopy(template)
        row["timestamp"] = (now - timedelta(seconds=size - i - 1)).isoformat().replace("+00:00", "Z")
        rows.append(row)
    return {"records": rows, "topology": history["topology"]}


def percentile95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(.95 * len(values)) - 1)]


def run_benchmark(sizes=(1, 12, 48, 100, 338, 1000)) -> list[dict]:
    rows = []
    for size in sizes:
        payload = payload_for_size(size)
        iterations = 20 if size == 1 else 12 if size == 12 else 8 if size == 48 else 5 if size == 100 else 3
        run_diagnosis(payload)  # warm-up
        durations = []
        for _ in range(iterations):
            start = time.perf_counter()
            run_diagnosis(payload)
            durations.append((time.perf_counter() - start) * 1000)
        tracemalloc.start()
        run_diagnosis(payload)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rows.append({"records": size, "iterations": iterations, "median_ms": statistics.median(durations),
                     "p95_ms": percentile95(durations), "records_per_second": size / (statistics.median(durations) / 1000),
                     "peak_python_mb": peak / (1024 * 1024)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "docs" / "PERFORMANCE.md"))
    args = parser.parse_args()
    results = run_benchmark()
    lines = ["# Diagnosis performance benchmark", "",
             f"Run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
             f"Environment: Python {platform.python_version()}, {platform.platform()}", "",
             "This measures one complete in-process `run_diagnosis()` call at several input sizes. It uses jittered synthetic link-congestion readings, one device, and the bundled topology. Each size is warmed up once; the table reports repeated-run median and 95th percentile latency. Peak memory is Python allocation traced by `tracemalloc`, not total process memory.", "",
             "These numbers describe this machine and software version. They are a repeatable baseline, not a service-level guarantee. The HTTP service and Streamlit rendering are not included.", "",
             "| Records per diagnosis | Timed runs | Median (ms) | P95 (ms) | Records/second | Peak traced Python memory (MiB) |",
             "|---:|---:|---:|---:|---:|---:|"]
    for row in results:
        lines.append(f"| {row['records']} | {row['iterations']} | {row['median_ms']:.2f} | {row['p95_ms']:.2f} | {row['records_per_second']:.0f} | {row['peak_python_mb']:.2f} |")
    lines += ["", "Re-run with `python scripts/performance_benchmark.py`. The benchmark creates fresh synthetic inputs for each size; it does not change the sample dataset or access a network device.", ""]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
