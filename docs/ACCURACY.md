# Randomized accuracy audit (seed 20261101, n=1000)

Truth is the generated primary fault. Twenty percent of cases receive a distinct second fault; a normal baseline with an injected fault is labeled by that fault. A low-confidence report still predicts its named cause; `other` means the system abstained or returned an ambiguous result, so this strict single-label matrix does not credit every correct alternative in a multi-fault report.

## Confusion matrix (rows = expected, columns = predicted)

| Expected \ Predicted | normal | Link congestion | Weak Wi-Fi | Hardware failure | Ethernet/interface fault | DNS/DHCP service failure | other |
|---|---|---|---|---|---|---|---|
| normal | 108 | 0 | 0 | 0 | 0 | 0 | 0 |
| Link congestion | 0 | 177 | 0 | 0 | 0 | 0 | 10 |
| Weak Wi-Fi | 0 | 8 | 152 | 0 | 0 | 0 | 13 |
| Hardware failure | 0 | 3 | 5 | 65 | 84 | 0 | 10 |
| Ethernet/interface fault | 0 | 4 | 12 | 0 | 157 | 0 | 27 |
| DNS/DHCP service failure | 0 | 6 | 2 | 0 | 2 | 142 | 13 |

Fuzz exceptions: 0

## Empirical confidence calibration by score decile

Correctness is exact single-label agreement, including abstentions in the lowest bin. These are empirical reliability measurements on this generated distribution, not production probabilities; no in-sample adjustment is applied to runtime scores.

| Score bin | Cases | Correct | Observed accuracy |
|---|---:|---:|---:|
| 0.0–0.1 | 61 | 0 | 0.0%
| 0.1–0.2 | 21 | 14 | 66.7%
| 0.2–0.3 | 222 | 143 | 64.4%
| 0.3–0.4 | 182 | 152 | 83.5%
| 0.4–0.5 | 1 | 0 | 0.0%
| 0.5–0.6 | 5 | 5 | 100.0%
| 0.6–0.7 | 149 | 149 | 100.0%
| 0.7–0.8 | 190 | 169 | 88.9%
| 0.8–0.9 | 64 | 64 | 100.0%
| 0.9–1.0 | 105 | 105 | 100.0%

## Current nine-scenario demo results

These fixed fixtures are evaluated separately from the randomized audit. Confidence is the displayed deterministic evidence score.

| Scenario | Status | Cause | Confidence |
|---|---|---|---:|
| normal | healthy | No fault detected | 80% |
| latency_spike | diagnosed | Latency spike | 31% |
| hardware_failure | diagnosed | Hardware failure | 95% |
| link_congestion | diagnosed | Link congestion | 87% |
| weak_wifi | diagnosed | Weak Wi-Fi | 51% |
| interface_fault | diagnosed | Ethernet/interface fault | 31% |
| dns_dhcp_failure | diagnosed | DNS/DHCP service failure | 72% |
| interoperability_failure | diagnosed | Link congestion | 67% |
| malformed_input | insufficient_evidence | Insufficient evidence to identify a probable root cause | 0% |
