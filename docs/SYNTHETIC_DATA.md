# Synthetic dataset generation

## Source and method

The linked Colab notebook uses Python's `random` module to generate one switch record with a timestamp, device ID, metrics, and status. The local generator follows its three baseline branches and adds the extra cases recommended in the challenge brief. It uses `random.Random(20261031)` so numeric values are repeatable for the same generator version and seed. Timestamps are assigned when the fixture is generated; they are synthetic too.

Generate the bundled fixture again from the project root:

```bash
python -m netcoop.data_generator --output data/sample_telemetry.json
```

The generator writes one example record for each of nine scenarios, plus a synthetic topology. It does not collect campus data, query network equipment, or represent measurements from IIT Bhubaneswar.

## Colab baseline ranges

| Scenario | Generated values |
|---|---|
| Normal | CPU 10–35%; link use 20–50%; loss 0%; latency 5–20 ms; jitter 1–5 ms; zero queue drops. |
| Latency spike | CPU 40–70%; link use 60–85%; loss 0.1–1.5%; latency 150–400 ms; jitter 30–80 ms; queue drops 0–50. |
| Hardware failure | CPU 99.9%; link use 100%; loss 15–30%; latency 500–1000 ms; queue drops 5,000–15,000; interface errors 100–500. |

These ranges match the linked Colab script. The original notebook itself has only these baseline branches.

## Added challenge scenarios

The local generator extends the baseline with high link utilization and drops for congestion; low signal strength and retransmissions for Wi-Fi; interface errors and packet loss for Ethernet; service state for DNS/DHCP; and deliberately malformed field names/units for interoperability and validation handling. These ranges are authored demo fixtures, not extra data from the Colab notebook.

The JSON dataset is included in the project archive and can also be downloaded from the dashboard's “What is this scenario using?” panel.
