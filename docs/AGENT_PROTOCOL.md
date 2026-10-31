# Agent message protocol: `agent_message_v1`

Every message is a JSON object with this envelope:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Must be `agent_message_v1`. |
| `message_id` | string | Unique message identifier. |
| `timestamp` | ISO 8601 UTC string | Message creation time. |
| `source_agent` | string | Sending specialist. |
| `target_agent` | string | Intended recipient (`orchestrator` or a specialist). |
| `status` | `ok`, `warning`, or `error` | Processing result. |
| `findings` | array of strings | Concise interpretations, not raw telemetry. |
| `evidence` | array of objects | `{device_id, metric, value, unit, interpretation}`. |
| `limitations` | array of strings | Missing or incompatible input that constrains interpretation. |

Canonical fields and units: `latency_ms` (ms), `jitter_ms` (ms), `packet_loss_pct` (%), `throughput_mbps` (Mbps), `bandwidth_mbps` (Mbps), `link_utilization_pct` (%), `cpu_utilization_pct` (%), `memory_utilization_pct` (%), `queue_drops` (count), `interface_errors` (count), `signal_strength_dbm` (dBm), `retransmissions_pct` (%), `service_status` (categorical), `device_status` (categorical).

## Responsibilities and handoffs

1. `performance_agent` evaluates latency, jitter, loss, throughput, utilization, and Wi-Fi quality.
2. `infrastructure_agent` evaluates CPU, memory, queues, interface errors, and device state.
3. `connectivity_agent` uses topology links and service status to infer the affected scope.
4. `correlation_agent` combines the preceding structured messages, ranks causes, calculates an evidence score, and may return insufficient evidence.
5. `reporting_agent` converts the correlated result into the challenge's unified JSON schema.

All messages are retained in order in the dashboard trace. Invalid schema versions, unrecognized units, and out-of-range metrics produce validation warnings. Unknown measurements are discarded; absent data is not interpreted as healthy.

## Confidence score

For a candidate cause, each independent evidence family contributes up to 0.30, then up to 0.10 is added for corroborating signals. Scores are capped at 0.95. The score is a rule-based evidence score, not a calibrated probability. A cause is reported only when its score is at least 0.42 and at least two independent agent families support it. Otherwise, status is `insufficient_evidence`.
