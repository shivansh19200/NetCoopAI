# Agent message protocol: `agent_message_v1`

The default mode uses **deterministic rule-based agents**; a bounded Groq reviewer is optional. Every message is an `agent_message_v1` JSON object and is validated against [`schema.json`](schema.json) both when created and when received. A malformed message is rejected with a clear error; diagnosis continues with the remaining valid messages.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Must be `agent_message_v1`. |
| `message_id` | string | Stable identifier used to correlate a run's handoffs. |
| `timestamp` | ISO 8601 UTC string | Message creation time. |
| `source_agent` | string | Sending specialist. |
| `target_agent` | string | Intended recipient. Specialist messages target `correlation_agent`; its result targets `reporting_agent`. |
| `status` | `ok`, `warning`, or `error` | Processing result. |
| `findings` | array of strings | Concise interpretations, not raw telemetry. |
| `evidence` | array of objects | `{device_id, metric, value, unit, interpretation}`; report evidence cites `source_message_id`. |
| `received_message_ids` | array of strings | IDs of upstream messages consumed by a directed handoff. |
| `limitations` | array of strings | Missing or incompatible input that constrains interpretation. |

Canonical fields and units: `latency_ms` (ms), `jitter_ms` (ms), `packet_loss_pct` (%), `throughput_mbps` (Mbps), `bandwidth_mbps` (Mbps), `link_utilization_pct` (%), `cpu_utilization_pct` (%), `memory_utilization_pct` (%), `queue_drops` (count), `interface_errors` (count), `signal_strength_dbm` (dBm), `retransmissions_pct` (%), `service_status` (categorical), `device_status` (categorical).

## Responsibilities and handoffs

1. `performance_agent` evaluates latency, jitter, loss, throughput, utilization, and Wi-Fi quality.
2. `infrastructure_agent` evaluates CPU, memory, queues, interface errors, and device state.
3. `connectivity_agent` uses topology links and service status to infer the affected scope.
4. `correlation_agent` combines the preceding structured messages, ranks causes, calculates an evidence score, and may return insufficient evidence.
5. `reporting_agent` converts the correlated result into the challenge's unified JSON schema.

Messages are retained in order in the dashboard trace. Correlation receives only the three specialist messages and records their IDs. The report cites the originating message ID for each supporting evidence item. Invalid telemetry schema versions, unrecognized units, and out-of-range metrics produce warnings. Unknown measurements are discarded; absent data is not interpreted as healthy.

## MCP adapter

`mcp_server.py` exposes `list_demo_scenarios`, `diagnose_telemetry`, and `diagnose_demo_scenario` tools. Read-only resources `netcoop://protocol` and `netcoop://sample-dataset` expose this protocol and the synthetic fixture. The MCP server calls the same validator and orchestrator as the dashboard.

## Confidence score

Confidence is a deterministic evidence score, not a calibrated probability. Repeated `(device_id, timestamp, metrics)` records are deduplicated, and corroboration counts distinct devices and metrics. At least three distinct signals can support a diagnosis from one family, capped at 0.55. If two candidate scores are within 0.05, status is `ambiguous` and the report recommends a discriminating measurement. Confidence penalties and fixed-seed scenario results are documented in [`ACCURACY.md`](ACCURACY.md).

## Optional model reviewer

When explicitly enabled, `groq_review_agent` receives the consolidated diagnostic report and specialist findings. Its response is validated against the `model_review` JSON Schema and added as an advisory section. It cannot change the rule-based root cause or confidence. If the provider is unavailable or returns invalid data, the deterministic report remains intact and the model message is marked as a warning. No model call is made by default.
