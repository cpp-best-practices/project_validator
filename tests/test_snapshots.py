"""Every fixture, compared with recorded snapshots: what the validator says about it (`<fixture>.json`: the results,
the answers and what it shows without judging, the behaviour a change in policy or in a question shows in), and what it
learned (`<fixture>.facts.json`: the facts and the project map, which a change in an extractor or in a fact type shows
in).

Refactorings must reproduce both; a deliberate change is recorded with `UPDATE_SNAPSHOTS=1 python3 -m unittest
tests.test_snapshots` and reviewed in the diff. The two are kept apart so that a change to how a fact is recorded is
reviewed as that, with the behaviour visibly unchanged, and so that a profile's pull request touches its own fixtures'
behaviour and only the facts the others share.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from project_validator.about import about
from project_validator.facts.tools import known_tools
from project_validator.plugins import discover
from project_validator.questions.answers import answers
from project_validator.runner import run_checks
from tests.support import FIXTURES, make_context

SNAPSHOTS = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def snapshots_of(fixture: Path) -> dict[str, dict[str, object]]:
    """The behaviour snapshot (`results`, `answers`) and the facts snapshot (`facts`, `map`) of a fixture, by the
    suffix of the file each is kept in."""
    context = make_context(fixture)
    reports = run_checks(discover().checks, context)
    behaviour: dict[str, object] = {
        "answers": answers(context),
        "results": {
            report.check.name: {
                "status": str(report.result.status),
                "message": report.result.message,
                "details": list(report.result.details),
            }
            for report in reports
        },
        "about": [detail.as_dict() for detail in about(context.facts)],
    }
    facts: dict[str, object] = {"facts": context.facts.as_dicts(), "map": context.structure.as_dict()}
    return {".json": behaviour, ".facts.json": facts}


def registry_snapshot() -> dict[str, object]:
    """What the validator tells users about its tools and checks, independent of any project: each tool's name,
    languages, the levels it can provide with how to get each (the text of every hint naming it), what it reads, and
    each check's name, description and aliases."""
    tools = sorted(
        (
            {
                "name": tool.name,
                "languages": sorted(tool.languages),
                "can": {aspect: dict(sorted(levels.items())) for aspect, levels in sorted(tool.can.items())},
                "reads": list(tool.reads),
                "required": sorted(tool.required),
            }
            for tool in known_tools()
        ),
        key=lambda tool: (str(tool["name"]), json.dumps(tool, sort_keys=True)),
    )
    checks = {
        check.name: {"description": check.description, "aliases": list(check.aliases)}
        for check in sorted(discover().checks, key=lambda check: check.name)
    }
    return {"checks": checks, "tools": tools}


def _render(snapshot: dict[str, object]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


class SnapshotTests(unittest.TestCase):
    def test_the_tools_and_checks_match_their_snapshot(self) -> None:
        path = SNAPSHOTS / "registry.json"
        actual = _render(registry_snapshot())
        if UPDATE:
            path.write_text(actual, encoding="utf-8")
        self.assertEqual(actual, path.read_text(encoding="utf-8"))

    def test_every_fixture_matches_its_snapshots(self) -> None:
        fixtures = sorted(path for path in FIXTURES.iterdir() if path.is_dir())
        self.assertTrue(fixtures)
        for fixture in fixtures:
            for suffix, snapshot in snapshots_of(fixture).items():
                with self.subTest(fixture=fixture.name, snapshot=suffix):
                    path = SNAPSHOTS / f"{fixture.name}{suffix}"
                    actual = _render(snapshot)
                    if UPDATE:
                        path.write_text(actual, encoding="utf-8")
                    self.assertEqual(actual, path.read_text(encoding="utf-8"))
