# NetCoop AI | Network diagnostics

A runnable Streamlit dashboard for topology-aware, multi-agent network fault diagnosis. The demo uses synthetic telemetry from the Colab generator linked in the hackathon brief; no production network is contacted or modified.

## Quick start

1. Install Python 3.10 or later.
2. From this folder, create an environment and install the packages:

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   streamlit run app.py
   ```

3. Choose a scenario in the left sidebar. The topology animates packet flow; the agent run generates a diagnosis and downloadable JSON report.

## What is included

- Five distinct agents: performance, infrastructure, connectivity, fault correlation, and recommendations/reporting.
- Versioned JSON agent envelopes with documented fields, units, validation, and a message trace.
- A topology diagram with continuously animated packets and a highlighted affected segment.
- Sample data for healthy operation, latency spike, hardware failure, link congestion, weak Wi-Fi, interface fault, DNS/DHCP service issue, and an interoperability failure.
- A malformed telemetry case, explicit missing-evidence handling, and structured diagnostic report export.
- Reproducible synthetic data generation. `colab_generator.ipynb` is the Colab notebook linked in the supplied brief. The baseline generator in `netcoop/data_generator.py` follows its `normal`, `latency_spike`, and `hardware_failure` branches; additional scenarios extend its fields and ranges for the brief's suggested test cases.

## Architecture

`app.py` loads a selected sample or uploaded JSON/CSV, runs the orchestrator, and renders the report, topology, agent trace, and telemetry. `netcoop/agents.py` contains five deterministic specialist agents. Each sends an `agent_message_v1` envelope with `message_id`, `timestamp`, `source_agent`, `target_agent`, `schema_version`, `status`, `findings`, `evidence`, and `limitations`. Measurements use the field names and units from the synthetic data (`latency_ms`, `packet_loss_pct`, `link_utilization_pct`, `cpu_utilization_pct`, `queue_drops`, `interface_errors`, `jitter_ms`, and `signal_strength_dbm`).

The orchestrator collects the specialist messages before invoking the correlation agent. Correlation ranks candidate causes from independent evidence families, caps confidence when evidence is sparse or conflicting, and returns `insufficient_evidence` if the score is below the documented threshold. The reporting agent creates a report with the fields required in the challenge: incident ID, status, suspected cause, confidence, affected devices, supporting evidence, alternative causes, recommended actions, evidence sources, and limitations. Findings are recommendations for an operator; the prototype performs no remediation.

## Confidence method

The rule-based correlator scores candidate causes by independent evidence families (performance, infrastructure, topology/service scope). Each matching family contributes up to 0.30; corroborating specific signals add up to 0.10, with a 0.95 cap. Confidence is therefore an evidence score, not a calibrated probability. A diagnosis requires a top score of 0.42 and at least two evidence items from distinct agent families. Otherwise the report says evidence is insufficient and lists what to collect next.

## Input and error handling

Upload a JSON object or a CSV with one row per device. Canonical metric names are preferred; common aliases such as `latency`, `packet_loss`, and `link_utilization` are normalized. Unknown units and invalid numeric ranges are excluded with warnings; missing metrics remain missing and cannot count as supporting evidence. The interoperability demo intentionally supplies an unknown schema version and incompatible unit. Invalid JSON, empty files, and absent metrics produce a visible input error or an insufficient-evidence report, not a fabricated diagnosis.

CSV columns: `timestamp`, `device_id`, `device_type`, `site`, `status`, followed by metric columns. Optional topology is represented in JSON as a `topology` object containing `devices` and `links` arrays.

## Synthetic data and test scenarios

The [Colab notebook linked in the hackathon brief](https://colab.research.google.com/drive/1xFOtO114qWICAxGisK9K6oOHoOxwvGi1) is included as `colab_generator.ipynb`; open it in Google Colab and run its single cell to generate baseline telemetry. The local dashboard is reproducible without Colab and does not need an API key. Run `python -m netcoop.data_generator --output data/sample_telemetry.json` to regenerate the bundled demo fixture. The generator uses a fixed seed for repeatable scenarios.

Scenarios are synthetic and are not campus measurements. DNS/DHCP scenarios model service-specific failure via `service_status`; the notebook itself does not generate service telemetry, so this is an explicit extension for the brief's suggested scenario.

## Project files

- `app.py` — Streamlit dashboard.
- `netcoop/agents.py` — message protocol, validation, agents, orchestration, and report assembly.
- `netcoop/data_generator.py` — Colab-derived synthetic generator and scenario extensions.
- `data/sample_telemetry.json` — generated demo scenarios.
- `docs/AGENT_PROTOCOL.md` — message contract, field definitions, units, and failure semantics.
- `colab_generator.ipynb` — source notebook linked from the PDF.

## Demo walkthrough

Select **Link congestion** and run diagnosis. Follow the animated path from gateway through the core switch to access devices, then inspect the performance and infrastructure evidence, the correlator's candidate ranking, and the JSON report. Switch to **Interoperability failure** to see schema/unit validation warnings and reduced confidence. Download the JSON report from the dashboard.

This prototype supports a reproducible live demo; record a three-to-five-minute screen capture separately if a demo video is required for submission.
