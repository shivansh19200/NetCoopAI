"""Local SQLite persistence for paused runs, reviews, and safe action simulations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WorkflowStore:
    def __init__(self, path: str | Path = "state/netcoop_workflows.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY, scenario TEXT NOT NULL,
                phase TEXT NOT NULL, payload_json TEXT NOT NULL,
                result_json TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
                decision TEXT NOT NULL, note TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS simulations (
                simulation_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
                action TEXT NOT NULL, result TEXT NOT NULL,
                created_at TEXT NOT NULL)""")

    def save_checkpoint(self, scenario: str, payload: Any, result: Any, phase: str = "paused") -> str:
        checkpoint_id = f"WF-{uuid.uuid4().hex[:10].upper()}"
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                (checkpoint_id, scenario, phase, json.dumps(payload), json.dumps(result), now, now),
            )
        return checkpoint_id

    def list_checkpoints(self, limit: int = 25) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT checkpoint_id, scenario, phase, created_at, updated_at FROM checkpoints ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_checkpoint(self, checkpoint_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)).fetchone()
        if row is None:
            return None
        checkpoint = dict(row)
        checkpoint["payload"] = json.loads(checkpoint.pop("payload_json"))
        checkpoint["result"] = json.loads(checkpoint.pop("result_json"))
        return checkpoint

    def mark_resumed(self, checkpoint_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE checkpoints SET phase = 'resumed', updated_at = ? WHERE checkpoint_id = ?", (utc_now(), checkpoint_id))

    def save_review(self, incident_id: str, decision: str, note: str = "") -> str:
        review_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as db:
            db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?)", (review_id, incident_id, decision, note, utc_now()))
        return review_id

    def save_simulation(self, incident_id: str, action: str) -> str:
        simulation_id = f"SIM-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as db:
            db.execute("INSERT INTO simulations VALUES (?, ?, ?, ?, ?)", (simulation_id, incident_id, action, "simulated_only_no_network_change", utc_now()))
        return simulation_id

    def recent_events(self, limit: int = 10) -> dict[str, list[dict]]:
        with self._connect() as db:
            reviews = [dict(r) for r in db.execute("SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
            simulations = [dict(r) for r in db.execute("SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
        return {"reviews": reviews, "simulations": simulations}
