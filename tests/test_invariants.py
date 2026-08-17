from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "architecture" / "invariants.registry.json"
DOC = ROOT / "docs" / "architecture" / "invariants.md"
EXPECTED_IDS = [f"I{index:02d}" for index in range(1, 26)]
STATUSES = {"enforced", "partial", "planned"}


def _load_registry() -> list[dict[str, object]]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _test_reference_exists(reference: str) -> bool:
    try:
        path_text, qualname = reference.split("::", 1)
    except ValueError:
        return False
    path = ROOT / path_text
    if not path.is_file() or not path_text.startswith("tests/") or not path_text.endswith(".py"):
        return False
    parts = qualname.split(".")
    if len(parts) not in {1, 2} or any(not part for part in parts):
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if len(parts) == 1:
        return any(isinstance(node, ast.FunctionDef) and node.name == parts[0] for node in tree.body)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == parts[0]:
            return any(isinstance(child, ast.FunctionDef) and child.name == parts[1] for child in node.body)
    return False


class InvariantRegistryTests(unittest.TestCase):
    def test_registry_contains_exact_frozen_ids_once(self) -> None:
        entries = _load_registry()
        ids = [str(entry.get("id")) for entry in entries]

        self.assertEqual(len(ids), len(set(ids)), "duplicate invariant IDs are not allowed")
        self.assertEqual(ids, EXPECTED_IDS)

    def test_registry_statuses_and_release_claims_are_valid(self) -> None:
        for entry in _load_registry():
            invariant_id = str(entry.get("id"))
            status = str(entry.get("status"))
            guarantee = str(entry.get("current_guarantee") or "")
            target_release = str(entry.get("planned_target_release") or "")
            self.assertIn(status, STATUSES, invariant_id)
            self.assertTrue(str(entry.get("title") or "").endswith("."), invariant_id)
            self.assertTrue(guarantee, invariant_id)
            if status == "planned":
                self.assertTrue(target_release, invariant_id)
                self.assertRegex(guarantee, r"\b[Pp]lanned\b")
                self.assertRegex(guarantee, r"\b[Nn]ot a current\b")
            if status == "enforced":
                self.assertFalse(target_release, invariant_id)
                self.assertNotRegex(guarantee, r"\b[Pp]lanned\b", invariant_id)
            if status == "partial":
                self.assertTrue(target_release, invariant_id)

    def test_enforced_invariants_reference_real_focused_tests(self) -> None:
        for entry in _load_registry():
            invariant_id = str(entry["id"])
            refs = entry.get("test_references")
            self.assertIsInstance(refs, list, invariant_id)
            if entry.get("status") == "enforced":
                self.assertGreater(len(refs), 0, invariant_id)
            for ref in refs:
                self.assertIsInstance(ref, str, invariant_id)
                self.assertTrue(_test_reference_exists(ref), f"{invariant_id} references missing test {ref}")

    def test_markdown_publishes_same_ids_and_links_registry(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("docs/architecture/invariants.registry.json", text)
        table_ids = re.findall(r"^\| (I\d{2}) \|", text, flags=re.MULTILINE)
        self.assertEqual(table_ids, EXPECTED_IDS)


if __name__ == "__main__":
    unittest.main()
