"""Reproducible acceptance checks for the NetCoop prototype."""

import unittest

from netcoop.agents import PROTOCOL, run_diagnosis
from netcoop.data_generator import SCENARIOS, build_demo_data


class NetCoopAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = build_demo_data()

    def test_all_documented_scenarios_are_present(self):
        self.assertEqual(SCENARIOS, [row["scenario"] for row in self.dataset["records"]])
        first = build_demo_data()
        for left, right in zip(self.dataset["records"], first["records"]):
            self.assertEqual(left["metrics"], right["metrics"])

    def test_normal_case_is_reported_as_healthy(self):
        record = next(r for r in self.dataset["records"] if r["scenario"] == "normal")
        result = run_diagnosis({"records": [record], "topology": self.dataset["topology"]})
        self.assertEqual("healthy", result["report"]["status"])
        self.assertEqual("No fault detected", result["report"]["suspected_root_cause"])
        self.assertGreaterEqual(result["report"]["confidence"], .8)

    def test_link_congestion_produces_supported_report(self):
        record = next(r for r in self.dataset["records"] if r["scenario"] == "link_congestion")
        result = run_diagnosis({"records": [record], "topology": self.dataset["topology"]})
        self.assertEqual("diagnosed", result["report"]["status"])
        self.assertEqual("Link congestion", result["report"]["suspected_root_cause"])
        self.assertTrue(result["report"]["supporting_evidence"])
        self.assertGreaterEqual(len(result["report"]["evidence_sources"]), 2)
        self.assertIn("HOSTEL_CORE_SW_01", result["report"]["affected_devices"])

    def test_service_fault_is_correlated_across_service_and_infrastructure_findings(self):
        record = next(r for r in self.dataset["records"] if r["scenario"] == "dns_dhcp_failure")
        result = run_diagnosis({"records": [record], "topology": self.dataset["topology"]})
        self.assertEqual("diagnosed", result["report"]["status"])
        self.assertEqual("DNS/DHCP service failure", result["report"]["suspected_root_cause"])
        self.assertGreaterEqual(len(result["report"]["evidence_sources"]), 2)

    def test_malformed_and_incompatible_data_is_reported(self):
        record = next(r for r in self.dataset["records"] if r["scenario"] == "interoperability_failure")
        result = run_diagnosis({"records": [record], "topology": self.dataset["topology"]})
        self.assertTrue(any("schema version" in warning for warning in result["warnings"]))
        self.assertTrue(any("incompatible" in warning for warning in result["warnings"]))
        malformed = next(r for r in self.dataset["records"] if r["scenario"] == "malformed_input")
        malformed_result = run_diagnosis({"records": [malformed]})
        self.assertEqual("insufficient_evidence", malformed_result["report"]["status"])
        self.assertTrue(malformed_result["warnings"])

    def test_missing_metrics_are_not_treated_as_healthy(self):
        result = run_diagnosis({"records": [{"device_id": "PARTIAL_NODE", "metrics": {}}]})
        self.assertEqual("insufficient_evidence", result["report"]["status"])
        self.assertEqual([], result["report"]["supporting_evidence"])
        self.assertIn("No above-threshold", " ".join(m["findings"][0] for m in result["agent_messages"][:3]))

    def test_structured_messages_from_all_five_agents(self):
        result = run_diagnosis({"records": self.dataset["records"][:1], "topology": self.dataset["topology"]})
        self.assertEqual(5, len(result["agent_messages"]))
        for message in result["agent_messages"]:
            self.assertEqual(PROTOCOL, message["schema_version"])
            self.assertTrue(message["source_agent"])
            self.assertIn("evidence", message)


if __name__ == "__main__":
    unittest.main()
