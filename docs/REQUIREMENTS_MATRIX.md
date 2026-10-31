# Hackathon requirements coverage

| Requirement | Implementation |
|---|---|
| Multiple collaborating agents | Five distinct agents emit findings that are consumed by correlation and reporting agents. |
| Agent interoperability | `agent_message_v1` JSON envelope and units are documented in `AGENT_PROTOCOL.md`. |
| Agent orchestration | `run_diagnosis()` validates, dispatches, correlates, and assembles one report. |
| Network fault diagnosis | Rule-based evidence correlation for congestion, Wi-Fi, interface, device, and DNS/DHCP cases. |
| Unified report | Required JSON fields, confidence, alternatives, actions, evidence sources, and limitations; dashboard download included. |
| Validation and error handling | Alias normalization, unit/schema checks, range validation, and clear insufficient-evidence behavior. |
| Reproducible testing and documentation | `tests/`, nine synthetic cases, setup instructions, protocol and data-generation documentation. |
| MCP (optional) | Local MCP tools for scenario listing and diagnosis; resources expose protocol and dataset. |
| Human review (optional) | Persisted operator decision and note for the report. |
| Pause/resume (optional) | SQLite checkpoint stores scenario, input, full report, and agent messages; resume from sidebar. |
| Interactive dashboard (optional) | Animated topology, telemetry table, report, candidate scores, and structured agent trace. |
| Automated remediation (optional) | Safe simulation event only; no device command or production network connection exists. |

Run the reproducible acceptance checks with `python -m unittest discover -s tests -v`.
