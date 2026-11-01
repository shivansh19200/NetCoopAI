# How the agents communicate

NetCoop agents exchange JSON messages so the same specialists can run in the dashboard or as separate HTTP services. Each message has a unique ID and a real UTC timestamp. A conversation ID groups messages from one diagnosis; a reply can point to the message it answers.

Messages use one of four types:

- `finding` — an agent shares what it observed.
- `task_request` — an agent asks another specialist to check something.
- `challenge` — the correlator asks for more evidence or flags uncertainty.
- `ack` — an agent confirms it handled a request.

Each specialist sends a capability card that lists the measurements it understands. It also sends normal observations, not only unusual ones. Normal observations help the correlator rule out possible causes.

## A typical diagnosis

1. The input adapter converts recognized units and vendor field names to the shared metric names.
2. Performance, infrastructure, and connectivity specialists assess the readings they understand.
3. The correlator compares the evidence and can ask a specialist a follow-up, such as whether CPU use is normal on a device.
4. The report includes the likely cause, evidence, confidence score, other possibilities, and suggested checks.

Repeated readings of the same metric on the same device are counted once. Each evidence item may list possible causes and how well they fit. The correlator checks those suggestions against the measurements and fixed evidence rules. Optional Groq suggestions cannot directly set the final verdict.

## Send requests over HTTP

Start the service with:

```bash
python -m netcoop.http_agents
```

It listens on `127.0.0.1:8765` by default and accepts JSON at `/agents/performance`, `/agents/infrastructure`, `/agents/connectivity`, `/agents/correlation`, and `/agents/reporting`. To have the dashboard or CLI use this service, set `NETCOOP_AGENT_URL` to `http://127.0.0.1:8765` before starting it. This sends requests through HTTP between processes instead of calling every specialist directly in the same process.

The optional MCP (Model Context Protocol) server is started with `mcp run mcp_server.py` and offers tools for listing scenarios and running diagnoses.

## Message fields

| Field | What it means |
|---|---|
| `schema_version` | Version of this message format (`agent_message_v1`). |
| `message_id` | Unique ID for this message. |
| `timestamp` | When the message was created, in UTC. |
| `message_type` | `finding`, `task_request`, `challenge`, or `ack`. |
| `conversation_id` | ID shared by messages from one diagnosis. |
| `in_reply_to` | ID of the message this one answers, or `null`. |
| `capability_card` | Measurements and tasks the sender supports. |
| `normalization` | Unit or field-name changes made to the input. |
| `source_agent` / `target_agent` | Who sent the message and who should receive it. |
| `status` | Whether the sender completed its work, had a warning, or failed. |
| `findings` | Short explanations of what the agent found. |
| `evidence` | Readings with device, metric, unit, interpretation, and possible causes. |
| `received_message_ids` | IDs of earlier messages used for this reply. |
| `limitations` | Missing or incompatible input that affects the result. |

## Shared measurement names

Agents use the same names and units: `latency_ms` (milliseconds), `jitter_ms` (milliseconds), `packet_loss_pct` (percent), `throughput_mbps` and `bandwidth_mbps` (Mbps), `link_utilization_pct`, `cpu_utilization_pct`, `memory_utilization_pct`, and `retransmissions_pct` (percent), `queue_drops` and `interface_errors` (counts), `signal_strength_dbm` (dBm), plus categorical `service_status` and `device_status`.

The adapter recognizes aliases such as `ifInErrors`, `rssi`, and `cpuUsage`; it also converts seconds to milliseconds and bits per second to Mbps. Conversions are listed in each message. If a percentage might be a fraction from 0 to 1, the adapter converts it and lowers confidence slightly because the intent is unclear. Booleans and infinite values are rejected. Missing data is not treated as a healthy reading.

## Confidence and validation

Confidence is a score based on evidence rules, not a probability. Repeated `(device, metric)` pairs are removed before independent sources are counted. Sparse or conflicting evidence can lower the score, and close competing causes can produce an unclear result. The dashboard shows the score breakdown and labels at or above 75% High, at or above 45% Medium, and lower scores Low. The [audit report](ACCURACY.md) shows observed results on generated cases.

Messages are checked against [`schema.json`](schema.json) when they are created and received. Invalid messages are rejected; diagnosis can continue with other valid messages. The dashboard replay preserves message order and shows the message IDs and any input conversions.

## Who does what

- `performance_agent` checks delay, jitter, packet loss, link use, throughput, and Wi-Fi quality.
- `infrastructure_agent` checks CPU, memory, queue drops, interface errors, and device state.
- `connectivity_agent` checks services and uses network links to map the affected area.
- `correlation_agent` compares the specialists' evidence, ranks possible causes, and may ask a follow-up question.
- `reporting_agent` turns the result into the final report.

The MCP server also provides the message format and sample data as read-only resources. It uses the same input checks and diagnosis code as the dashboard.
