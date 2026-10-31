"""Optional Groq advisory reviewer for deterministic rule-based diagnoses."""
from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from netcoop.agents import SCHEMA

GROQ_MODEL = "openai/gpt-oss-20b"
MODEL_REVIEW_SCHEMA = SCHEMA["$defs"]["model_review"]


def _review_context(report: dict, messages: list[dict]) -> dict:
    """Send only the compact report and specialist findings needed for a review."""
    return {
        "rule_report": {
            "status": report["status"],
            "suspected_root_cause": report["suspected_root_cause"],
            "confidence": report["confidence"],
            "supporting_evidence": report["supporting_evidence"],
            "ranked_candidates": [
                {"cause": c["cause"], "score": c["score"], "distinct_signals": c["distinct_signals"]}
                for c in report["ranked_candidates"][:4]
            ],
        },
        "agent_findings": [
            {
                "message_id": message["message_id"],
                "source_agent": message["source_agent"],
                "findings": message["findings"],
                "evidence": message["evidence"],
            }
            for message in messages
            if message.get("source_agent") in {"performance_agent", "infrastructure_agent", "connectivity_agent", "correlation_agent"}
        ],
    }


def review_diagnosis(report: dict, messages: list[dict], api_key: str, model: str = GROQ_MODEL, client: Any = None) -> dict:
    """Ask Groq for a schema-validated advisory; it cannot replace the rule verdict."""
    if client is None:
        from groq import Groq

        client = Groq(api_key=api_key, timeout=25.0, max_retries=0)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an advisory network diagnosis reviewer. Review only the supplied deterministic rule report and agent findings. "
                    "Do not invent measurements, devices, or incidents. Check whether the evidence supports the rule verdict, name plausible alternatives "
                    "only when grounded in the supplied candidates or measurements, and give practical measurement checks. The deterministic verdict and "
                    "confidence are authoritative and must not be changed. Return only the requested structured object."
                ),
            },
            {"role": "user", "content": json.dumps(_review_context(report, messages), separators=(",", ":"))},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "netcoop_model_review",
                "strict": True,
                "schema": MODEL_REVIEW_SCHEMA,
            },
        },
        temperature=0.1,
        max_completion_tokens=700,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq returned an empty review.")
    review = json.loads(content)
    errors = list(Draft202012Validator(MODEL_REVIEW_SCHEMA).iter_errors(review))
    if errors:
        raise ValueError(f"Groq review did not match the review schema: {errors[0].message}")
    if review["status"] != "reviewed":
        raise ValueError("Groq did not return a completed review.")
    return review
