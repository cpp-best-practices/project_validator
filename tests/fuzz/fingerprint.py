"""A short digest of a fuzz target and of the validator modules it imports: `python tests/fuzz/fingerprint.py json`.

CI keys each target's cached corpus on it, so a change to the target's parser saves the corpus under a new key (starting
from the previous one), while a change elsewhere in the tree leaves the target's cache alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Run in a fresh interpreter, so that only what the target itself imports is loaded; atheris is stubbed, since the
# target only needs its `instrument_imports` context manager to import.
_LIST_MODULES = """
import contextlib, json, runpy, sys
from unittest import mock
atheris = mock.MagicMock()
atheris.instrument_imports.side_effect = contextlib.nullcontext
sys.modules["atheris"] = atheris
runpy.run_path(sys.argv[1], run_name="fuzz_target")
loaded = [module for name, module in list(sys.modules.items()) if name.split(".")[0] == "project_validator"]
files = (getattr(module, "__file__", None) for module in loaded)
print(json.dumps([file for file in files if file]))
"""


def imported_modules(harness: Path) -> list[str]:
    """The files of the `project_validator` modules `harness` imports, relative to the repository root, sorted."""
    completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed script and a harness path
        [sys.executable, "-c", _LIST_MODULES, str(harness)],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    files = json.loads(completed.stdout)
    return sorted(Path(file).resolve().relative_to(ROOT).as_posix() for file in files)


def digest(root: Path, paths: Iterable[str]) -> str:
    """A digest of the names and contents of `paths` under `root`."""
    hashed = hashlib.sha256()
    for path in paths:
        hashed.update(path.encode() + b"\0" + (root / path).read_bytes() + b"\0")
    return hashed.hexdigest()[:16]


def fingerprint(target: str) -> str:
    harness = Path(__file__).resolve().parent / f"fuzz_{target}.py"
    return digest(ROOT, [harness.relative_to(ROOT).as_posix(), *imported_modules(harness)])


if __name__ == "__main__":
    print(fingerprint(sys.argv[1]))
