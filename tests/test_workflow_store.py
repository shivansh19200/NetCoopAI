"""Persistence checks for pause/resume, reviews, and remediation simulation."""

import tempfile
import unittest
from pathlib import Path

from netcoop.workflow_store import WorkflowStore


class WorkflowStoreTests(unittest.TestCase):
    def test_checkpoint_review_and_simulation_survive_store_reopen(self):
        project_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=project_root) as directory:
            db_path = Path(directory) / "workflow.sqlite3"
            store = WorkflowStore(db_path)
            checkpoint_id = store.save_checkpoint(
                "link_congestion",
                {"records": [{"device_id": "SW1"}]},
                {"report": {"incident_id": "INC-1"}, "agent_messages": [{"source_agent": "performance_agent"}]},
            )
            review_id = store.save_review("INC-1", "Request more telemetry", "Need a second sample")
            simulation_id = store.save_simulation("INC-1", "Inspect queue policy")

            reopened = WorkflowStore(db_path)
            checkpoint = reopened.load_checkpoint(checkpoint_id)
            self.assertEqual("link_congestion", checkpoint["scenario"])
            self.assertEqual("INC-1", checkpoint["result"]["report"]["incident_id"])
            reopened.mark_resumed(checkpoint_id)
            self.assertEqual("resumed", reopened.load_checkpoint(checkpoint_id)["phase"])
            events = reopened.recent_events()
            self.assertEqual(review_id, events["reviews"][0]["review_id"])
            self.assertEqual(simulation_id, events["simulations"][0]["simulation_id"])
            self.assertEqual("simulated_only_no_network_change", events["simulations"][0]["result"])


if __name__ == "__main__":
    unittest.main()
