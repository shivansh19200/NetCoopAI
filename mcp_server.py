"""Optional NetCoop MCP server. Run locally with `mcp run mcp_server.py`."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server import MCPServer

from netcoop.agents import run_diagnosis
from netcoop.data_generator import SCENARIOS, build_demo_data

mcp = MCPServer("NetCoop AI diagnostics")
ROOT = Path(__file__).parent
SAMPLE_PATH = ROOT / "data" / "sample_telemetry.json"


def _sample() -> dict:
    if SAMPLE_PATH.exists():
        return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return build_demo_data()


@mcp.tool()
def list_demo_scenarios() -> list[dict[str, str]]:
    """List available synthetic NetCoop telemetry scenarios."""
    return [{"scenario": item} for item in SCENARIOS]


@mcp.tool()
def diagnose_telemetry(telemetry_json: str) -> dict:
    """Validate telemetry JSON and return a multi-agent diagnostic report."""
    try:
        payload = json.loads(telemetry_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"}
    result = run_diagnosis(payload)
    return {"report": result["report"], "warnings": result["warnings"], "ranked_candidates": result["ranked_candidates"], "agent_messages": result["agent_messages"]}


@mcp.tool()
def diagnose_demo_scenario(scenario: str) -> dict:
    """Run the agents on one bundled synthetic scenario by its scenario key."""
    if scenario not in SCENARIOS:
        return {"error": f"Unknown scenario. Choose one of: {', '.join(SCENARIOS)}"}
    sample = _sample()
    record = next((row for row in sample["records"] if row.get("scenario") == scenario), None)
    if record is None:
        return {"error": f"No telemetry record is available for scenario `{scenario}`."}
    result = run_diagnosis({"records": [record], "topology": sample["topology"]})
    return {"report": result["report"], "warnings": result["warnings"], "ranked_candidates": result["ranked_candidates"], "agent_messages": result["agent_messages"]}


@mcp.resource("netcoop://protocol")
def protocol_resource() -> str:
    """Read the documented agent message contract and metric units."""
    return (ROOT / "docs" / "AGENT_PROTOCOL.md").read_text(encoding="utf-8")


@mcp.resource("netcoop://sample-dataset")
def sample_dataset_resource() -> str:
    """Read the bundled synthetic topology and scenario telemetry."""
    return json.dumps(_sample(), indent=2)


if __name__ == "__main__":
    mcp.run()
