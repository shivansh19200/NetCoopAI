# Results from the 1,000-case check

This check creates 1,000 made-up scenarios with varied readings. One in five includes a second, different problem. Some cases leave out fields or include invalid values. The test compares the main expected problem with the system's main answer.

This is a controlled test of generated data, not a measure of accuracy on a real network. When the system returns “other”, it either did not have enough evidence or reported an ambiguous result. In a two-problem case, the table does not give credit for a correct second cause unless it was the main answer.

## Main answer compared with expected answer

Rows are the expected result; columns are what the system returned. `other` means the system held back or found the result unclear.

| Expected ↓ / Returned → | Normal | Link congestion | Weak Wi-Fi | Hardware failure | Ethernet / interface fault | DNS / DHCP service failure | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal | 108 | 0 | 0 | 0 | 0 | 0 | 0 |
| Link congestion | 0 | 185 | 0 | 0 | 0 | 0 | 2 |
| Weak Wi-Fi | 0 | 8 | 152 | 0 | 0 | 0 | 13 |
| Hardware failure | 0 | 3 | 5 | 65 | 0 | 0 | 94 |
| Ethernet / interface fault | 8 | 5 | 12 | 0 | 140 | 0 | 35 |
| DNS / DHCP service failure | 0 | 6 | 2 | 0 | 0 | 142 | 15 |

The system handled all fuzzed inputs without an exception. Its biggest weakness in this run was hardware failure: it often returned “other” instead of naming the expected cause. Some weak Wi-Fi and interface cases were mistaken for link congestion or another cause.

## How the confidence score lined up with results

The score is a rule-based evidence score, not a probability that the answer is right. This table groups cases by the score shown by the system and shows how often the main answer exactly matched the expected one. Empty bins had no cases.

| Score shown | Cases | Exact matches | Match rate |
|---|---:|---:|---:|
| 0.0–0.1 | 251 | 108 | 43.0% |
| 0.1–0.2 | 15 | 14 | 93.3% |
| 0.2–0.3 | 145 | 126 | 86.9% |
| 0.3–0.4 | 235 | 212 | 90.2% |
| 0.4–0.5 | 14 | 13 | 92.9% |
| 0.5–0.6 | 11 | 11 | 100.0% |
| 0.6–0.7 | 143 | 143 | 100.0% |
| 0.7–0.8 | 186 | 165 | 88.7% |
| 0.8–0.9 | 0 | — | — |
| 0.9–1.0 | 0 | — | — |

The score bands are an empirical calibration check: they show how often each score range matched the expected answer. The test results are not used to tune scores on those same cases. The dashboard labels scores of 75% or above High, 45% or above Medium, and lower scores Low. These labels do not guarantee a matching real-world success rate.

The run is repeatable with seed `20261101`:

```bash
python scripts/accuracy_audit.py
```
