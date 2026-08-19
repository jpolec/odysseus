from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from odysseus import __version__


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_release_assets_module():  # noqa: ANN202
    path = REPOSITORY_ROOT / "scripts" / "build-release-assets.py"
    spec = importlib.util.spec_from_file_location("build_release_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseConsistencyTests(unittest.TestCase):
    def test_release_asset_metadata_covers_public_artifacts(self) -> None:
        module = _load_release_assets_module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "dist"
            dist.mkdir()
            wheel = dist / f"odysseus_agents-{__version__}-py3-none-any.whl"
            sdist = dist / f"odysseus_agents-{__version__}.tar.gz"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")
            (dist / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

            generated = module.build_release_metadata(dist, root)

            self.assertEqual({path.name for path in generated}, {"SHA256SUMS", "SBOM.spdx.json", "PROVENANCE.json"})
            sbom = json.loads((root / "SBOM.spdx.json").read_text(encoding="utf-8"))
            provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
            sums = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()

            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertEqual(sbom["packages"][0]["versionInfo"], __version__)
            self.assertEqual(provenance["predicateType"], "https://slsa.dev/provenance/v1")
            self.assertEqual({subject["name"] for subject in provenance["subject"]}, {wheel.name, sdist.name})
            expected_names = {wheel.name, sdist.name, "SBOM.spdx.json", "PROVENANCE.json"}
            self.assertEqual({line.split("  ", 1)[1] for line in sums}, expected_names)
            self.assertNotIn(".gitignore", (root / "SHA256SUMS").read_text(encoding="utf-8"))
            for line in sums:
                digest, name = line.split("  ", 1)
                target = dist / name if (dist / name).exists() else root / name
                self.assertEqual(digest, hashlib.sha256(target.read_bytes()).hexdigest())

    def test_release_consistency_verifier_passes_current_checkout(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/verify-release-consistency.py"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
