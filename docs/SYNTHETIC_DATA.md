# About the sample data

The project includes made-up readings for exploring the dashboard. They are not collected from campus equipment and should not be used to claim how a real network is performing.

There are two fixtures for different jobs:

- `data/sample_telemetry.json` has one record for each of nine scenarios. It is used by tests and command-line examples.
- `data/demo_timeseries.json` has 86 records. Seven scenarios have 12 jittered readings each for one device, four minutes apart (a 44-minute timeline); malformed and compatibility examples each have one record. The dashboard uses this fixture so its graphs can show changes over time.

These 86 rows are useful for the demo, not a representative network dataset. The separate 1,000-case audit generates new synthetic cases; it does not turn these rows into real or independent field measurements. See [`ACCURACY.md`](ACCURACY.md) for the audit and [`PERFORMANCE.md`](PERFORMANCE.md) for timing results.

The original Colab notebook produces one switch reading with a timestamp, device ID, metrics, and status. The local generator keeps its three baseline cases, then adds examples for the other project scenarios. It uses a fixed random seed (`20261031`), so regenerating the same version gives repeatable values. Generated timestamps are examples too.

Regenerate the bundled fixture from the project folder:

```bash
python -m netcoop.data_generator --output data/sample_telemetry.json
```

The standard file contains one record for each of nine scenarios and a sample network map. It does not query real devices. Regenerate the longer history with:

```bash
python -m netcoop.data_generator --timeseries --output data/demo_timeseries.json
```

The app moves the built-in sample timestamps forward when it loads them. It still checks uploaded timestamps for staleness.

## Baseline readings from the notebook

| Scenario | Example ranges |
|---|---|
| Normal | CPU 10–35%; link use 20–50%; packet loss 0%; latency 5–20 ms; jitter 1–5 ms; no queue drops. |
| Latency spike | CPU 40–70%; link use 60–85%; packet loss 0.1–1.5%; latency 150–400 ms; jitter 30–80 ms; queue drops 0–50. |
| Hardware failure | CPU 99.9%; link use 100%; packet loss 15–30%; latency 500–1,000 ms; queue drops 5,000–15,000; interface errors 100–500. |

Those three ranges come from the linked Colab notebook. The local project adds further demo examples: busy links and dropped packets, weak Wi-Fi, wired port errors, DNS/DHCP service trouble, and deliberately confusing field names or units. Those additions are authored test cases, not readings from the notebook or from a real network.

The generator used by the 1,000-case audit also varies values, sometimes combines two problems, sometimes leaves fields out, and sometimes inserts malformed values. See [`ACCURACY.md`](ACCURACY.md) for the results.
