# Accuracy and scenario expectations

NetCoop AI's default diagnosis uses deterministic rule-based agents. The optional Groq reviewer does not change the verdict or confidence. The verdict is derived from supplied measurements and explicit rules; confidence is a relative evidence score, not a calibrated probability. These expected results are checked by `tests/test_acceptance_repo.py` with fixed seed `20261031`.

| Scenario | Expected verdict | Actual with bundled seed | Notes |
|---|---|---|---|
| normal | Not enough evidence | Not enough evidence | No fault threshold crossed |
| latency_spike | Latency spike | Latency spike (0.31) | High latency, jitter, and loss signals |
| hardware_failure | Hardware failure | Hardware failure (0.55) | Critical status, CPU ≥95%, and interface errors |
| link_congestion | Link congestion | Link congestion (0.87) | High link use and queue drops on the same device |
| weak_wifi | Weak Wi-Fi | Weak Wi-Fi (0.51) | Weak signal and retransmissions with latency/loss |
| interface_fault | Ethernet/interface fault | Ethernet/interface fault (0.31) | High interface error count |
| dns_dhcp_failure | DNS/DHCP service failure | DNS/DHCP service failure (0.72) | Service availability signals |
| interoperability_failure | Link congestion (lower confidence) | Link congestion (0.67) | Unsupported schema and incompatible units incur penalties |
| malformed_input | Not enough evidence | Not enough evidence | Invalid records are ignored with warnings |

## Confidence penalties

Before penalties, candidate score is `0.36 × supporting agent families + 0.05 × additional distinct device/metric signals`, capped at `0.95`. A single-family diagnosis with at least three signals is capped at `0.55`. The specific critical-status + CPU ≥95% + high-interface-errors hardware signature receives a priority score of `0.95`, while its final single-family confidence remains capped. Close candidates within `0.05` produce an ambiguous report. These weights are tuned against the fixed-seed scenarios and remain heuristic scores, not trained or statistically calibrated probabilities.

| Input condition | Penalty |
|---|---:|
| Unsupported telemetry schema version | -0.15 |
| Each ignored metric | -0.05, capped at -0.20 |
| Device missing from supplied topology | -0.10 |
| No usable topology | -0.10 |
| Agent execution failure | -0.05 per failed agent |
| Conflicting agent claims | -0.05 per recorded conflict |

Penalties cannot reduce confidence below zero. Repeated copies of the same `(device_id, timestamp, metrics)` record do not add evidence or confidence.
