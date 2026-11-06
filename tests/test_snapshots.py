"""The results and project map of every fixture, compared with recorded snapshots.

Refactorings must reproduce the snapshots; a deliberate change in behaviour is recorded with
`UPDATE_SNAPSHOTS=1 python3 -m unittest tests.test_snapshots` and reviewed in the diff.
"""

import json
import os
import unittest
from pathlib import Path

from project_validator.plugins import discover
from project_validator.runner import run_checks
from tests.support import FIXTURES, make_context

SNAPSHOTS = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def snapshot_of(fixture: Path) -> dict[str, object]:
    context = make_context(fixture)
    reports = run_checks(discover().checks, context)
    return {
        "map": context.structure.as_dict(),
        "facts": context.facts.as_dicts(),
        "results": {
            report.check.name: {
                "status": str(report.result.status),
                "message": report.result.message,
                "details": list(report.result.details),
            }
            for report in reports
        },
    }


def _render(snapshot: dict[str, object]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


class SnapshotTests(unittest.TestCase):
    def test_every_fixture_matches_its_snapshot(self) -> None:
        fixtures = sorted(path for path in FIXTURES.iterdir() if path.is_dir())
        self.assertTrue(fixtures)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                path = SNAPSHOTS / f"{fixture.name}.json"
                actual = _render(snapshot_of(fixture))
                if UPDATE:
                    path.write_text(actual, encoding="utf-8")
                self.assertEqual(actual, path.read_text(encoding="utf-8"))
