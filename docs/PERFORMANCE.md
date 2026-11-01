# Diagnosis performance benchmark

This measures one complete in-process `run_diagnosis()` call at several input sizes. It uses jittered synthetic link-congestion readings, one device, and the bundled topology. Each size is warmed up once; the table reports repeated-run median and 95th percentile latency. Peak memory is Python allocation traced by `tracemalloc`, not total process memory.

These numbers describe this machine and software version. They are a repeatable baseline, not a service-level guarantee. The HTTP service and Streamlit rendering are not included.

| Records per diagnosis | Timed runs | Median (ms) | P95 (ms) | Records/second | Peak traced Python memory (MiB) |
|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 3.83 | 3.92 | 261 | 0.06 |
| 12 | 12 | 17.81 | 18.12 | 674 | 0.26 |
| 48 | 8 | 63.45 | 65.05 | 756 | 0.87 |
| 100 | 5 | 136.95 | 141.94 | 730 | 1.76 |
| 338 | 3 | 2723.18 | 2819.11 | 124 | 5.91 |
| 1000 | 3 | 8065.95 | 8250.48 | 124 | 17.34 |

Re-run with `python scripts/performance_benchmark.py`. The benchmark creates fresh synthetic inputs for each size; it does not change the sample dataset or access a network device.
