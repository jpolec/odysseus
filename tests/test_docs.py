from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SecurityDocumentationRegistryTests(unittest.TestCase):
    def test_threat_model_is_published_and_registered(self) -> None:
        threat_model = ROOT / "docs" / "security" / "threat-model.md"
        security = ROOT / "SECURITY.md"
        master_plan = ROOT / "docs" / "architecture" / "MASTER_PLAN.md"

        self.assertTrue(threat_model.exists())
        self.assertIn("docs/security/threat-model.md", security.read_text(encoding="utf-8"))
        self.assertIn("docs/security/threat-model.md", master_plan.read_text(encoding="utf-8"))

    def test_threat_model_names_required_boundaries_threats_and_status(self) -> None:
        text = (ROOT / "docs" / "security" / "threat-model.md").read_text(encoding="utf-8")
        lowered = text.lower()

        required_boundaries = [
            "human operator",
            "host kernel",
            "repository content",
            "agent output",
            "skills",
            "external mcp",
            "ci output",
            "webhook payloads",
            "runtime profile",
            "credentials",
            "browser and http api",
            "durable storage",
        ]
        for boundary in required_boundaries:
            self.assertIn(boundary, lowered)

        required_threats = [
            "prompt injection",
            "malicious build",
            "dependency",
            "filesystem",
            "credential access",
            "data exfiltration",
            "forged callbacks",
            "poisoned evidence",
        ]
        for threat in required_threats:
            self.assertIn(threat, lowered)

        status_requirements = [
            "there is no secret broker",
            "not cas",
            "general inbound webhook receiver is not implemented",
            "not a current odysseus security boundary",
            "does not implement or verify kernel isolation",
            "planned controls are not current guarantees",
        ]
        for requirement in status_requirements:
            self.assertIn(requirement, lowered)


if __name__ == "__main__":
    unittest.main()
