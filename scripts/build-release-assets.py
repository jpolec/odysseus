#!/usr/bin/env python3
"""Create checksum, SBOM, and provenance files for release artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odysseus import __version__


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(args: list[str], fallback: str = "") -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback


def _artifact_subject(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "digest": {"sha256": _sha256(path)},
        "size": path.stat().st_size,
    }


def build_release_metadata(dist_dir: Path, output_dir: Path) -> list[Path]:
    dist_dir = dist_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = sorted(path for path in dist_dir.iterdir() if path.is_file())
    if not artifacts:
        raise SystemExit(f"no release artifacts found in {dist_dir}")

    created_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    commit = os.environ.get("GITHUB_SHA") or _git_value(["rev-parse", "HEAD"])
    repository = os.environ.get("GITHUB_REPOSITORY", "jpolec/odysseus")
    ref = os.environ.get("GITHUB_REF_NAME") or _git_value(["describe", "--tags", "--exact-match"], f"v{__version__}")
    workflow = os.environ.get("GITHUB_WORKFLOW", "local-release-build")

    sbom_path = output_dir / "SBOM.spdx.json"
    provenance_path = output_dir / "PROVENANCE.json"
    checksums_path = output_dir / "SHA256SUMS"

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"odysseus-agents-{__version__}-release-artifacts",
        "documentNamespace": f"https://github.com/{repository}/releases/tag/{ref}/sbom",
        "creationInfo": {
            "created": created_at,
            "creators": ["Tool: odysseus-release-assets"],
        },
        "packages": [
            {
                "name": "odysseus-agents",
                "SPDXID": "SPDXRef-Package-odysseus-agents",
                "versionInfo": __version__,
                "downloadLocation": f"https://github.com/{repository}",
                "filesAnalyzed": False,
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(path)} for path in artifacts],
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/odysseus-agents@{__version__}",
                    }
                ],
            }
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-odysseus-agents",
            }
        ],
    }
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [_artifact_subject(path) for path in artifacts],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/odysseus-agents/release-proof",
                "externalParameters": {"ref": ref, "version": __version__},
                "internalParameters": {"workflow": workflow},
                "resolvedDependencies": [
                    {
                        "uri": f"git+https://github.com/{repository}.git",
                        "digest": {"gitCommit": commit},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": f"https://github.com/{repository}/actions/workflows/release.yml"},
                "metadata": {
                    "invocationId": os.environ.get("GITHUB_RUN_ID", "local"),
                    "startedOn": created_at,
                    "finishedOn": created_at,
                },
            },
        },
    }
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    checksum_assets = artifacts + [sbom_path, provenance_path]
    checksums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in sorted(checksum_assets, key=lambda item: item.name)),
        encoding="utf-8",
    )
    return [sbom_path, provenance_path, checksums_path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", default="dist", type=Path)
    parser.add_argument("--output-dir", default=".", type=Path)
    args = parser.parse_args()
    for path in build_release_metadata(args.dist_dir, args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
