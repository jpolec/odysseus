#!/usr/bin/env python3
"""Verify CI, release, and version declarations stay coherent."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odysseus import __version__


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _failures() -> list[str]:
    failures: list[str] = []
    pyproject = tomllib.loads(_read("pyproject.toml"))
    if pyproject.get("project", {}).get("dynamic") != ["version"]:
        failures.append("pyproject.toml must keep project.version dynamic")
    dynamic = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    if dynamic.get("version", {}).get("attr") != "odysseus.__version__":
        failures.append("pyproject.toml must derive the package version from odysseus.__version__")

    expected_snippets = {
        "README.md": [f"version-{__version__}", f"odysseus proof --release {__version__}"],
        "VERSION.md": [f"**{__version__} "],
        "PROOF.md": [f"For the {__version__} release candidate"],
        "docs/USAGE.md": [f"proof --release {__version__}"],
    }
    for relative, snippets in expected_snippets.items():
        content = _read(relative)
        for snippet in snippets:
            if snippet not in content:
                failures.append(f"{relative} is missing {snippet!r}")

    workflow_expectations = {
        ".github/workflows/ci.yml": ["name: Fast CI", "name: unit", "name: compatibility (3.10)", "scripts/verify-release-consistency.py"],
        ".github/workflows/security.yml": ["name: Security", "name: security"],
        ".github/workflows/installer-smoke.yml": ["name: Installer Smoke", "name: installer-smoke"],
        ".github/workflows/main-proof.yml": ["name: Main Proof", "scripts/release-proof.sh"],
        ".github/workflows/release.yml": [
            "name: Release Proof",
            "scripts/release-proof.sh",
            "scripts/build-release-assets.py",
            "SBOM.spdx.json",
            "PROVENANCE.json",
            "SHA256SUMS",
        ],
    }
    for relative, snippets in workflow_expectations.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"{relative} is missing")
            continue
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in content:
                failures.append(f"{relative} is missing {snippet!r}")
        for number, line in enumerate(content.splitlines(), 1):
            match = re.search(r"\buses:\s*([^@\s]+)@([^\s#]+)", line)
            if not match:
                continue
            reference = match.group(2)
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                failures.append(f"{relative}:{number} action is not pinned to a 40-character SHA")

    release_docs = _read("PROOF.md")
    required_phrases = [
        "Fast CI / unit",
        "Fast CI / compatibility (3.10)",
        "Security / security",
        "Installer Smoke / installer-smoke",
        "Main Proof / release-proof",
        "Release Proof / release-proof",
        "SBOM.spdx.json",
        "PROVENANCE.json",
        "SHA256SUMS",
    ]
    for phrase in required_phrases:
        if phrase not in release_docs:
            failures.append(f"PROOF.md is missing release governance phrase {phrase!r}")

    package_manifest = _read("scripts/build-release-assets.py")
    if "https://slsa.dev/provenance/v1" not in package_manifest or "SPDX-2.3" not in package_manifest:
        failures.append("release asset builder must emit SLSA provenance and SPDX SBOM metadata")
    return failures


def main() -> int:
    failures = _failures()
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"valid": True, "version": __version__}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
