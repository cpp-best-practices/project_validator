from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from typing import Any, cast

from project_validator import yaml_support

ROOT = Path(__file__).parent.parent


QUALITY_GATES = {
    "lint": "ruff check",
    "formatting": "ruff format --check",
    "typing": "mypy",
    "copy-paste-detection": "jscpd",
    "function-limits": "lizard --length",
}


def _job(name: str) -> dict[str, Any]:
    workflow = cast(dict[str, Any], yaml_support.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")))
    return cast(dict[str, Any], workflow["jobs"][name])


def _commands(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


class QualityGateTests(unittest.TestCase):
    def test_each_quality_gate_is_its_own_single_platform_job(self) -> None:
        for name, command in QUALITY_GATES.items():
            with self.subTest(job=name):
                job = _job(name)
                self.assertEqual(job["runs-on"], "ubuntu-latest")
                self.assertIn(command, _commands(job))

    def test_copy_paste_detection_fails_on_any_clone(self) -> None:
        config = json.loads((ROOT / ".jscpd.json").read_text(encoding="utf-8"))
        self.assertEqual(config["threshold"], 0)

    def test_type_checking_is_strict(self) -> None:
        settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertTrue(settings["tool"]["mypy"]["strict"])
