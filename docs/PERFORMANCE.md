# Diagnosis performance benchmark

Run date: 2026-11-01 04:13 UTC
Environment: Python 3.12.10, Windows-11-10.0.26200-SP0

This measures one complete in-process diagnosis call at several input sizes. Up to 1,000 rows are jittered link-congestion samples from one device; the 5,000-row case uses one healthy sample each from 5,000 devices. Each size is warmed up once; the table reports repeated-run median and 95th percentile latency. Peak memory is Python allocation traced by tracemalloc, not total process memory.

These numbers describe this machine and software version. They are a repeatable baseline, not a service-level guarantee. The HTTP service and Streamlit rendering are not included.

| Records per diagnosis | Timed runs | Median (ms) | P95 (ms) | Records/second | Peak traced Python memory (MiB) |
|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 8.12 | 13.45 | 123 | 0.10 |
| 12 | 12 | 28.72 | 44.52 | 418 | 0.35 |
| 48 | 8 | 19.82 | 32.98 | 2422 | 1.13 |
| 100 | 5 | 46.21 | 53.19 | 2164 | 2.27 |
| 5000 | 1 | 221.31 | 221.31 | 22593 | not measured |

Re-run with `python scripts/performance_benchmark.py`. The benchmark creates fresh synthetic inputs for each size; it does not change the sample dataset or access a network device.
