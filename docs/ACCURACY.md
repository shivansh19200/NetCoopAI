# Randomized accuracy audit (seed 20261101, n=1000)

Truth is the generated primary fault. Twenty percent of cases receive a distinct second fault; a normal baseline with an injected fault is labeled by that fault. `other` means the system abstained or returned an ambiguous multi-cause result, so this strict single-label matrix does not credit every correct alternative in a multi-fault report.

## Confusion matrix (rows = expected, columns = predicted)

| Expected \ Predicted | normal | Link congestion | Weak Wi-Fi | Hardware failure | Ethernet/interface fault | DNS/DHCP service failure | other |
|---|---|---|---|---|---|---|---|
| normal | 108 | 0 | 0 | 0 | 0 | 0 | 0 |
| Link congestion | 0 | 185 | 0 | 0 | 0 | 0 | 2 |
| Weak Wi-Fi | 0 | 8 | 152 | 0 | 0 | 0 | 13 |
| Hardware failure | 0 | 3 | 5 | 65 | 0 | 0 | 94 |
| Ethernet/interface fault | 8 | 5 | 12 | 0 | 140 | 0 | 35 |
| DNS/DHCP service failure | 0 | 6 | 2 | 0 | 0 | 142 | 15 |

Fuzz exceptions: 0

## Empirical confidence calibration by score decile

Correctness is exact single-label agreement, including abstentions in the lowest bin. These are empirical reliability measurements on this generated distribution, not production probabilities; no in-sample adjustment is applied to runtime scores. The app labels scores >=0.75 High, >=0.45 Medium, and lower scores Low.

| Score bin | Cases | Correct | Observed accuracy |
|---|---:|---:|---:|
| 0.0–0.1 | 251 | 108 | 43.0%
| 0.1–0.2 | 15 | 14 | 93.3%
| 0.2–0.3 | 145 | 126 | 86.9%
| 0.3–0.4 | 235 | 212 | 90.2%
| 0.4–0.5 | 14 | 13 | 92.9%
| 0.5–0.6 | 11 | 11 | 100.0%
| 0.6–0.7 | 143 | 143 | 100.0%
| 0.7–0.8 | 186 | 165 | 88.7%
| 0.8–0.9 | 0 | 0 | —
| 0.9–1.0 | 0 | 0 | —
