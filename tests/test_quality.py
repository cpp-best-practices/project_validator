import json
import tomllib
import unittest
from pathlib import Path
from typing import Any, cast

from project_validator import yaml_support

ROOT = Path(__file__).parent.parent


def _quality_job() -> dict[str, Any]:
    workflow = cast(dict[str, Any], yaml_support.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")))
    return cast(dict[str, Any], workflow["jobs"]["quality"])


def _quality_commands() -> str:
    return "\n".join(step.get("run", "") for step in _quality_job()["steps"])


class QualityGateTests(unittest.TestCase):
    def test_quality_job_runs_on_a_single_platform(self) -> None:
        self.assertEqual(_quality_job()["runs-on"], "ubuntu-latest")

    def test_quality_job_lints_formats_and_type_checks(self) -> None:
        commands = _quality_commands()
        for command in ("ruff check", "ruff format --check", "mypy"):
            with self.subTest(command=command):
                self.assertIn(command, commands)

    def test_quality_job_detects_copy_paste(self) -> None:
        self.assertIn("jscpd", _quality_commands())

    def test_copy_paste_detection_fails_on_any_clone(self) -> None:
        config = json.loads((ROOT / ".jscpd.json").read_text(encoding="utf-8"))
        self.assertEqual(config["threshold"], 0)

    def test_type_checking_is_strict(self) -> None:
        settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertTrue(settings["tool"]["mypy"]["strict"])
