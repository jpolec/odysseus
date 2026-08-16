#!/usr/bin/env python3
"""Build Odysseus source and wheel artifacts without network access.

This is a release-proof fallback for the zero-runtime-dependency package when
the normal isolated PEP 517 build cannot fetch its build backend. It mirrors the
project metadata and installed data files declared in pyproject.toml closely
enough for the package smoke test to install the wheel through uvx and boot the
real CLI/web assets.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path


NAME = "odysseus-agents"
DIST = "odysseus_agents"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odysseus import __version__  # noqa: E402

DATA_FILES = {
    "share/odysseus/web": ["web/index.html", "web/app.js", "web/styles.css", "web/odysseus-icon.svg"],
    "share/odysseus/skills/api-contracts": ["skills/api-contracts/SKILL.md"],
    "share/odysseus/skills/database-change": ["skills/database-change/SKILL.md"],
    "share/odysseus/skills/dependency-upgrade": ["skills/dependency-upgrade/SKILL.md"],
    "share/odysseus/skills/documentation-maintenance": ["skills/documentation-maintenance/SKILL.md"],
    "share/odysseus/skills/frontend-accessibility": ["skills/frontend-accessibility/SKILL.md"],
    "share/odysseus/skills/incident-debugging": ["skills/incident-debugging/SKILL.md"],
    "share/odysseus/skills/performance-review": ["skills/performance-review/SKILL.md"],
    "share/odysseus/skills/security-review": ["skills/security-review/SKILL.md"],
    "share/odysseus/skills/test-strategy": ["skills/test-strategy/SKILL.md"],
    "share/odysseus/scripts": ["scripts/demo.py", "scripts/session-meta.py"],
    "share/odysseus/installer": ["install.sh"],
    "share/odysseus/tmux": ["codex_session_manager.tmux"],
}


def _metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.4",
            f"Name: {NAME}",
            f"Version: {__version__}",
            "Summary: Zero-runtime-dependency orchestration for coding agents and tmux",
            "Author: Jakub Polec",
            "License-Expression: MIT",
            "Requires-Python: >=3.10",
            "Description-Content-Type: text/markdown",
            "Classifier: Development Status :: 3 - Alpha",
            "Classifier: Environment :: Console",
            "Classifier: Operating System :: MacOS",
            "Classifier: Operating System :: POSIX :: Linux",
            "Classifier: Programming Language :: Python :: 3",
            "Classifier: Programming Language :: Python :: 3.10",
            "Classifier: Programming Language :: Python :: 3.11",
            "Classifier: Programming Language :: Python :: 3.12",
            "Classifier: Programming Language :: Python :: 3.13",
            "Classifier: Topic :: Software Development :: Version Control :: Git",
            "Project-URL: Homepage, https://github.com/jpolec/odysseus",
            "Project-URL: Documentation, https://github.com/jpolec/odysseus#readme",
            "Project-URL: Issues, https://github.com/jpolec/odysseus/issues",
            "",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        ]
    )


def _wheel_metadata() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: odysseus-offline-package-proof",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _entry_points() -> str:
    return "[console_scripts]\nodysseus = odysseus.cli:main\n"


def _hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}"


def _write_zip(path: Path, files: list[tuple[str, bytes]]) -> None:
    record_name = f"{DIST}-{__version__}.dist-info/RECORD"
    record_rows: list[list[str]] = []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
            record_rows.append([name, _hash(data), str(len(data))])
        record_rows.append([record_name, "", ""])
        output = io.StringIO()
        csv.writer(output, lineterminator="\n").writerows(record_rows)
        archive.writestr(record_name, output.getvalue().encode("utf-8"))


def _wheel_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in sorted((ROOT / "odysseus").glob("*.py")):
        files.append((f"odysseus/{path.name}", path.read_bytes()))
    for target_dir, sources in DATA_FILES.items():
        for source in sources:
            source_path = ROOT / source
            data_name = f"{DIST}-{__version__}.data/data/{target_dir}/{source_path.name}"
            files.append((data_name, source_path.read_bytes()))
    dist_info = f"{DIST}-{__version__}.dist-info"
    files.extend(
        [
            (f"{dist_info}/METADATA", _metadata().encode("utf-8")),
            (f"{dist_info}/WHEEL", _wheel_metadata().encode("utf-8")),
            (f"{dist_info}/entry_points.txt", _entry_points().encode("utf-8")),
            (f"{dist_info}/top_level.txt", b"odysseus\n"),
            (f"{dist_info}/licenses/LICENSE", (ROOT / "LICENSE").read_bytes()),
        ]
    )
    return files


def _sdist_files() -> list[tuple[str, bytes]]:
    files = [
        ("LICENSE", (ROOT / "LICENSE").read_bytes()),
        ("README.md", (ROOT / "README.md").read_bytes()),
        ("pyproject.toml", (ROOT / "pyproject.toml").read_bytes()),
        ("codex_session_manager.tmux", (ROOT / "codex_session_manager.tmux").read_bytes()),
        ("install.sh", (ROOT / "install.sh").read_bytes()),
        ("PKG-INFO", _metadata().encode("utf-8")),
    ]
    for directory in ("odysseus", "web"):
        for path in sorted((ROOT / directory).glob("*")):
            if path.is_file():
                files.append((str(path.relative_to(ROOT)), path.read_bytes()))
    for target_dir, sources in DATA_FILES.items():
        del target_dir
        for source in sources:
            source_path = ROOT / source
            files.append((str(source_path.relative_to(ROOT)), source_path.read_bytes()))
    return sorted(dict(files).items())


def _write_sdist(path: Path) -> None:
    prefix = f"{DIST}-{__version__}"
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, data in _sdist_files():
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            info.mode = 0o644
            info.mtime = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
            archive.addfile(info, io.BytesIO(data))


def main() -> int:
    out_dir = Path(os.environ.get("ODYSSEUS_OFFLINE_DIST", "") or "dist").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_sdist(out_dir / f"{DIST}-{__version__}.tar.gz")
    _write_zip(out_dir / f"{DIST}-{__version__}-py3-none-any.whl", _wheel_files())
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
