"""The leaderboard (`leaderboard/`, upstream #295): the manifest is complete and consistent, entries are checked
before they join, and the nightly results become boards, project pages, history and badges. Nothing here fetches:
evaluation runs on projects made on the spot, and GitHub's answers are passed in."""

from __future__ import annotations

import contextlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

from leaderboard import SEED, Entry, ManifestError, by_name, entries, parse
from leaderboard.__main__ import PREVIEW_MARKER, check, main
from leaderboard.evaluation import evaluate, failed, fetch, write
from leaderboard.history import movement, ranked, read_history, record
from leaderboard.rules import BOARDS, MOST_KB, Repository, changed, duplicates, problems
from leaderboard.site import badge, build, sparkline
from project_validator.core import Context, ExtractionError
from project_validator.score import LEVEL_NAMES, SCORE_VERSION
from tests.support import FIXTURES

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

NOW = datetime(2026, 11, 18, 3, 17, tzinfo=UTC)

PUBLIC = Repository(found=True, license="MIT", size_kb=1000)
ENTRY = Entry(name="owner/repo", language="Rust", consent="https://github.com/owner/repo/issues/1")


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = entries()

    def test_the_seed_list_has_one_project_per_language(self) -> None:
        self.assertEqual(len(self.entries), 28)
        languages = [entry.language for entry in self.entries]
        self.assertEqual(sorted(set(languages)), sorted(languages))
        self.assertLessEqual(set(languages), BOARDS)

    def test_compiler_explorer_is_the_typescript_seed(self) -> None:
        (entry,) = by_name(["compiler-explorer/compiler-explorer"], self.entries)
        self.assertEqual(entry.language, "TypeScript")

    def test_every_entry_is_well_formed_and_listed_once(self) -> None:
        self.assertEqual(duplicates(self.entries), [])
        for entry in self.entries:
            with self.subTest(entry=entry.name):
                self.assertEqual(problems(entry, PUBLIC), [])
                self.assertTrue(entry.seed)

    def test_entries_are_sorted_by_language(self) -> None:
        languages = [entry.language.lower() for entry in self.entries]
        self.assertEqual(languages, sorted(languages))


class ParseTests(unittest.TestCase):
    def test_every_field(self) -> None:
        (entry,) = parse(
            '[[project]]\nname = "o/r"\nlanguage = "Go"\nconsent = "seed"\nbranch = "dev"\n'
            'auxiliary = ["scripts/"]\nexclude = ["testdata"]\nlicense = "MIT"\n'
        )
        self.assertEqual(
            entry,
            Entry(
                name="o/r",
                language="Go",
                consent=SEED,
                branch="dev",
                auxiliary=("scripts/",),
                exclude=("testdata",),
                license="MIT",
            ),
        )
        self.assertEqual((entry.slug, entry.url), ("o--r", "https://github.com/o/r"))

    def test_an_empty_manifest_lists_nothing(self) -> None:
        self.assertEqual(parse(""), [])

    def test_mistakes_are_named(self) -> None:
        cases = {
            '[[project]]\nname = "o/r"\nlanguage = "Go"\n': "o/r: missing consent",
            '[[project]]\nname = "o/r"\nlanguage = "Go"\nconsent = "seed"\nbranches = "x"\n': (
                "unknown field(s) branches"
            ),
            '[[project]]\nname = "o/r"\nlanguage = "Go"\nconsent = "seed"\nexclude = "x"\n': "expected a list",
            "[[project]\n": "does not parse",
        }
        for text, message in cases.items():
            with self.subTest(text=text), self.assertRaises(ManifestError) as raised:
                parse(text)
            self.assertIn(message, str(raised.exception))

    def test_by_name_needs_every_name_listed(self) -> None:
        with self.assertRaisesRegex(KeyError, "not on the leaderboard: x/y"):
            by_name(["x/y"], [ENTRY])


class EntryRuleTests(unittest.TestCase):
    def test_a_public_licensed_repository_with_consent_may_join(self) -> None:
        self.assertEqual(problems(ENTRY, PUBLIC), [])

    def test_each_rule(self) -> None:
        cases = [
            (Entry(name="not a name", language="Rust", consent=SEED), PUBLIC, "is not a GitHub owner/repo"),
            (Entry(name="o/r", language="Klingon", consent=SEED), PUBLIC, "`Klingon` is not a board"),
            (Entry(name="o/r", language="Rust", consent="yes please"), PUBLIC, "`consent` must link"),
            (ENTRY, Repository(found=False), "is not a public repository"),
            (ENTRY, Repository(found=True, private=True), "is not a public repository"),
            (ENTRY, Repository(found=True, archived=True, license="MIT"), "is archived"),
            (ENTRY, Repository(found=True, license="NOASSERTION"), "licence (NOASSERTION) is not"),
            (ENTRY, Repository(found=True, license=None), "licence (none) is not"),
            (ENTRY, Repository(found=True, license="MIT", size_kb=MOST_KB + 1), "more than the 2000 MB limit"),
        ]
        for entry, repository, message in cases:
            with self.subTest(message=message):
                found = problems(entry, repository)
                self.assertEqual(len(found), 1, found)
                self.assertIn(message, found[0])

    def test_a_missing_repository_is_not_checked_further(self) -> None:
        self.assertEqual(len(problems(Entry(name="o/r", language="?", consent="x"), Repository(found=False))), 3)

    def test_an_entry_names_its_licence_when_github_can_not_tell(self) -> None:
        named = Entry(name="o/r", language="Rust", consent=SEED, license="MPL-2.0")
        self.assertEqual(problems(named, Repository(found=True, license="NOASSERTION")), [])
        self.assertTrue(problems(Entry(name="o/r", language="Rust", consent=SEED, license="WTFPL"), PUBLIC))

    def test_duplicates_ignore_case(self) -> None:
        self.assertEqual(duplicates([ENTRY, Entry(name="Owner/Repo", language="Go", consent=SEED)]), ["owner/repo"])

    def test_changed_entries_are_the_new_and_the_edited(self) -> None:
        edited = Entry(name="owner/repo", language="Go", consent=SEED)
        new = Entry(name="new/one", language="Go", consent=SEED)
        other = Entry(name="same/one", language="Go", consent=SEED)
        self.assertEqual(changed([ENTRY, other], [edited, other, new]), [edited, new])


@contextlib.contextmanager
def _directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as name:
        yield Path(name)


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - argv list, no shell
        ["git", "-C", str(directory), "-c", "user.name=t", "-c", "user.email=t@t", *arguments],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _result(name: str, level: int, percent: float, **extra: object) -> dict[str, object]:
    """A night's result, scored `percent` at `level`, as `evaluate` writes it."""
    cells = extra.pop("cells", [])
    return {
        "name": name,
        "language": extra.pop("language", "Rust"),
        "commit": extra.pop("commit", "a" * 40),
        "validator": "v" * 40,
        "evaluated": "2026-11-18T03:17:00Z",
        "score": {
            "version": SCORE_VERSION,
            "percent": percent,
            "level": level,
            "level_name": LEVEL_NAMES[level],
            "filled": 3,
            "slots": 4,
            "summary": extra.pop("summary", f"{math.floor(percent)}% · Level {level} {LEVEL_NAMES[level]}"),
            "cells": cells,
            "next_steps": extra.pop("next_steps", []),
        },
        **extra,
    }


def _line(date: str, commit: str, level: int, percent: float) -> dict[str, object]:
    """A night's history line."""
    numbers = {"version": SCORE_VERSION, "percent": percent, "level": level, "filled": 3, "slots": 4}
    return {"date": date, "commit": commit, "validator": "v" * 40, **numbers}


def _step(**overrides: object) -> dict[str, object]:
    """A next step as the score's JSON has it: the project's own coverage slot, unless overridden."""
    defaults: dict[str, object] = {"check": "coverage", "ecosystem": "", "unit": "", "tier": "project"}
    defaults |= {"status": "FAIL", "level": 2, "points": 1.0, "needed_for": None, "completes": False}
    return defaults | overrides


def _cell(check: str, *tools: str) -> dict[str, object]:
    return {
        "check": check,
        "level": 2,
        "ecosystem": "Rust",
        "unit": ".",
        "tier": "core",
        "status": "PASS",
        "tools": list(tools),
        "weight": 1.0,
        "filled": 1.0,
        "extra": 0,
    }


class EvaluationTests(unittest.TestCase):
    ENTRY = Entry(name="o/well", language="Python", consent=SEED)

    def test_a_project_is_scored_with_every_check(self) -> None:
        with _directory() as root:
            shutil.copytree(FIXTURES / "well_configured_python", root / "p")
            result = evaluate(self.ENTRY, root / "p", commit="c" * 40, validator="v" * 40, now=NOW)
        self.assertEqual(
            {key: result[key] for key in ("name", "language", "seed", "commit", "validator", "evaluated", "unknowns")},
            {
                "name": "o/well",
                "language": "Python",
                "seed": True,
                "commit": "c" * 40,
                "validator": "v" * 40,
                "evaluated": "2026-11-18T03:17:00Z",
                "unknowns": 0,
            },
        )
        scored, checks = result["score"], result["checks"]
        if not isinstance(scored, dict) or not isinstance(checks, list):
            self.fail(result)
        self.assertEqual(scored["version"], SCORE_VERSION)
        self.assertGreaterEqual(scored["level"], 1)
        self.assertIn({"check": "license", "status": "PASS", "message": "the project is licensed under MIT"}, checks)
        self.assertNotIn("error", result)

    def test_the_entry_s_auxiliary_and_exclude_reach_the_validator(self) -> None:
        with _directory() as root:
            shutil.copytree(FIXTURES / "well_configured_python", root / "p")
            shutil.copytree(FIXTURES / "bare_cpp", root / "p" / "examples" / "c")
            percents = {}
            for label, entry in (
                ("plain", self.ENTRY),
                ("auxiliary", Entry(name="o/well", language="Python", consent=SEED, auxiliary=("example",))),
                ("excluded", Entry(name="o/well", language="Python", consent=SEED, exclude=("examples",))),
            ):
                scored = evaluate(entry, root / "p", commit="c", validator="v")["score"]
                if not isinstance(scored, dict):
                    self.fail(scored)
                percents[label] = scored["percent"]
        self.assertLess(percents["plain"], percents["auxiliary"])
        self.assertLess(percents["auxiliary"], percents["excluded"])

    def test_an_extraction_failure_is_recorded_without_the_checkout_s_path(self) -> None:
        with _directory() as root:
            shutil.copytree(FIXTURES / "well_configured_python", root / "p")
            broken = ExtractionError("facts", ValueError(f"{(root / 'p').resolve()}/setup.cfg broke"))
            with mock.patch.object(Context, "extraction_error", new_callable=mock.PropertyMock, return_value=broken):
                result = evaluate(self.ENTRY, root / "p", commit="c", validator="v")
        self.assertIn("<checkout>/setup.cfg broke", str(result["error"]))
        self.assertNotIn(str(root), str(result["error"]))

    def test_a_project_that_can_not_be_fetched_is_unscored_with_why(self) -> None:
        self.assertEqual(
            failed(self.ENTRY, "git fetch failed: no such repository", validator="v", now=NOW),
            {
                "name": "o/well",
                "language": "Python",
                "seed": True,
                "validator": "v",
                "evaluated": "2026-11-18T03:17:00Z",
                "error": "git fetch failed: no such repository",
            },
        )

    def test_results_are_written_by_slug(self) -> None:
        with _directory() as out:
            path = write({"name": "o/r", "b": 1, "a": "é"}, out / "results")
            self.assertEqual(path.name, "o--r.json")
            self.assertEqual(path.read_text(encoding="utf-8"), '{\n  "a": "é",\n  "b": 1,\n  "name": "o/r"\n}\n')


@unittest.skipUnless(shutil.which("git"), "needs git")
class FetchTests(unittest.TestCase):
    def test_the_head_of_the_branch_is_fetched_and_refetched(self) -> None:
        with _directory() as root:
            upstream = root / "upstream"
            upstream.mkdir()
            _git(upstream, "init", "--quiet", "-b", "main")
            (upstream / "a.txt").write_text("one\n")
            _git(upstream, "add", ".")
            _git(upstream, "commit", "--quiet", "-m", "one")
            first = _git(upstream, "rev-parse", "HEAD")
            entry = Entry(name="o/r", language="Go", consent=SEED)
            directory, commit = fetch(entry, root / "cache", url=upstream.as_uri())
            self.assertEqual((commit, (directory / "a.txt").read_text()), (first, "one\n"))
            (upstream / "a.txt").write_text("two\n")
            _git(upstream, "commit", "--quiet", "-am", "two")
            (directory / "stray.txt").write_text("left by an earlier run\n")
            directory, commit = fetch(entry, root / "cache", url=upstream.as_uri())
            self.assertEqual(
                (commit, (directory / "a.txt").read_text()), (_git(upstream, "rev-parse", "HEAD"), "two\n")
            )
            self.assertFalse((directory / "stray.txt").exists())

    def test_a_named_branch_and_a_missing_repository(self) -> None:
        with _directory() as root:
            upstream = root / "upstream"
            upstream.mkdir()
            _git(upstream, "init", "--quiet", "-b", "main")
            _git(upstream, "commit", "--quiet", "--allow-empty", "-m", "main")
            _git(upstream, "checkout", "--quiet", "-b", "dev")
            (upstream / "dev.txt").write_text("dev\n")
            _git(upstream, "add", ".")
            _git(upstream, "commit", "--quiet", "-m", "dev")
            _git(upstream, "checkout", "--quiet", "main")
            entry = Entry(name="o/r", language="Go", consent=SEED, branch="dev")
            directory, _ = fetch(entry, root / "cache", url=upstream.as_uri())
            self.assertTrue((directory / "dev.txt").is_file())
            with self.assertRaisesRegex(RuntimeError, "^o/gone: git fetch failed: "):
                fetch(Entry(name="o/gone", language="Go", consent=SEED), root / "cache", url=(root / "no").as_uri())


class HistoryTests(unittest.TestCase):
    def _night(self, data: Path, date: str, *results: dict[str, object]) -> list[str]:
        with _directory() as results_directory:
            for result in results:
                write(result, results_directory)
            return record(results_directory, data, date)

    def test_each_night_is_one_history_line_and_the_last_becomes_previous(self) -> None:
        with _directory() as data:
            self.assertEqual(self._night(data, "2026-11-17", _result("o/r", 1, 50)), ["o/r"])
            self.assertFalse((data / "previous" / "o--r.json").exists())
            self._night(data, "2026-11-18", _result("o/r", 2, 75, commit="b" * 40))
            history = read_history(data / "history" / "o--r.jsonl")
            self.assertEqual(history, [_line("2026-11-17", "a" * 40, 1, 50), _line("2026-11-18", "b" * 40, 2, 75)])
            previous = json.loads((data / "previous" / "o--r.json").read_text())
            self.assertEqual(previous["score"]["level"], 1)
            self.assertEqual(json.loads((data / "latest" / "o--r.json").read_text())["score"]["level"], 2)

    def test_a_rerun_of_a_night_replaces_it(self) -> None:
        with _directory() as data:
            self._night(data, "2026-11-17", _result("o/r", 1, 50))
            self._night(data, "2026-11-18", _result("o/r", 1, 60))
            self._night(data, "2026-11-18", _result("o/r", 1, 70))
            history = read_history(data / "history" / "o--r.jsonl")
            self.assertEqual([line["percent"] for line in history], [50, 70])
            self.assertEqual(json.loads((data / "previous" / "o--r.json").read_text())["score"]["percent"], 50)

    def test_an_unscored_night_is_kept(self) -> None:
        with _directory() as data:
            self._night(data, "2026-11-18", failed(EvaluationTests.ENTRY, "gone", validator="v"))
            (line,) = read_history(data / "history" / "o--well.jsonl")
            self.assertIsNone(line["level"])

    def test_a_missing_history_is_empty(self) -> None:
        self.assertEqual(read_history(Path("/nonexistent/history.jsonl")), [])


class MovementTests(unittest.TestCase):
    def test_tools_that_arrived_or_left_and_the_numbers(self) -> None:
        before = _result("o/r", 1, 50, cells=[_cell("static-analysis", "clippy"), _cell("coverage", "grcov")])
        after = _result("o/r", 2, 62.5, commit="b" * 40, cells=[_cell("static-analysis", "clippy", "cargo-deny")])
        self.assertEqual(
            movement(before, after),
            ["+cargo-deny (static-analysis)", "-grcov (coverage)", "Level 1 → 2", "+12.5 points"],
        )

    def test_a_change_without_a_new_commit_is_the_validator_s(self) -> None:
        self.assertEqual(
            movement(_result("o/r", 1, 50), _result("o/r", 1, 40)),
            ["-10.0 points", "same commit: the validator changed"],
        )

    def test_no_change_and_a_first_night(self) -> None:
        self.assertEqual(movement(_result("o/r", 1, 50), _result("o/r", 1, 50)), [])
        self.assertEqual(movement(None, _result("o/r", 1, 50)), ["new on the board"])
        self.assertEqual(movement(failed(EvaluationTests.ENTRY, "x", validator="v"), _result("o/r", 1, 50)), [])


class RankingTests(unittest.TestCase):
    def test_the_score_then_the_level_then_the_name_and_the_unscored_last(self) -> None:
        results = [
            failed(EvaluationTests.ENTRY, "x", validator="v"),
            _result("a/tie", 1, 90),
            _result("b/high", 2, 40),
            _result("c/extra", 4, 104),
            _result("d/tie", 2, 90),
            _result("e/tie", 1, 90),
        ]
        self.assertEqual(
            [result["name"] for result in ranked(results)], ["c/extra", "d/tie", "a/tie", "e/tie", "b/high", "o/well"]
        )


class SiteTests(unittest.TestCase):
    LISTED = (
        Entry(name="o/first", language="Rust", consent=SEED),
        Entry(name="o/second", language="Go", consent="https://example.org/ok"),
        Entry(name="o/broken", language="Go", consent=SEED),
    )

    # The second night's result for o/first: up a level, a new commit, two checks judged with --allow-unknown.
    FIRST = _result(
        "o/first",
        2,
        75,
        commit="b" * 40,
        seed=True,
        unknowns=2,
        cells=[_cell("static-analysis", "clippy | lint")],
        next_steps=[
            _step(check="fuzz-testing", ecosystem="Rust", unit=".", tier="core", status="WARN", level=3)
            | {"points": 6.25, "needed_for": 3, "completes": True}
        ],
    )

    def _data(self, data: Path) -> None:
        second = _result("o/second", 1, 50, language="Go")
        with _directory() as results:
            write(_result("o/first", 1, 50), results)
            write(second, results)
            record(results, data, "2026-11-17")
        with _directory() as results:
            write(self.FIRST, results)
            write(second, results)
            write(failed(self.LISTED[2], "git fetch failed", validator="v"), results)
            write(_result("gone/away", 4, 100), results)  # recorded once, since removed from the list
            record(results, data, "2026-11-18")

    def test_before_the_first_night_the_board_lists_the_projects(self) -> None:
        pages, files = build(self.LISTED, None, "https://o.github.io/p/")
        self.assertEqual(set(pages), {"leaderboard/index.html"})
        self.assertIn("No nightly results yet", pages["leaderboard/index.html"])
        self.assertIn("- [o/first](https://github.com/o/first) (Rust)", pages["leaderboard/index.html"])
        self.assertEqual(files, {"leaderboard/data/latest.json": "[]\n"})

    def test_the_boards_rank_every_listed_project(self) -> None:
        with _directory() as data:
            self._data(data)
            pages, _ = build(self.LISTED, data, "https://o.github.io/p/")
        board = pages["leaderboard/index.html"]
        self.assertIn(
            "| 1 | [o/first](projects/o--first.md) | Rust | 75% | 2 Analysis "
            "| +clippy \\| lint (static-analysis), Level 1 → 2, +25.0 points |",
            board,
        )
        self.assertIn("| 2 | [o/second](projects/o--second.md) | Go | 50% | 1 Foundations | - |", board)
        self.assertIn("| 3 | [o/broken](projects/o--broken.md) | Go | - | - | error: git fetch failed |", board)
        self.assertNotIn("gone/away", board)
        go_board = board.split("### Go", 1)[1]
        self.assertIn("| 1 | [o/second](projects/o--second.md) | 50% | 1 Foundations | - |", go_board)
        self.assertLess(board.index("### Go"), board.index("### Rust"))

    def test_a_project_page(self) -> None:
        with _directory() as data:
            self._data(data)
            pages, files = build(self.LISTED, data, "https://o.github.io/p/")
        page = pages["leaderboard/projects/o--first.html"]
        self.assertTrue(page.startswith("# o/first\n"))
        for expected in (
            "- A seed: awaiting a maintainer's confirmation",
            f"- Commit evaluated: [bbbbbbbbbbbb](https://github.com/o/first/commit/{'b' * 40})",
            f"score version {SCORE_VERSION}",
            "- 2 check(s) judged by what could be read",
            "**75% · Level 2 Analysis**",
            "<svg ",
            "| `fuzz-testing` | Rust in . | WARN | +6.2 | completes Level 3 |",
            "| `static-analysis` | 2 | Rust | . | core | PASS | clippy \\| lint | 1.0 of 1.0 | 0 |",
            "https://img.shields.io/endpoint?url=https://o.github.io/p/leaderboard/badges/o--first.json",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, page)
        self.assertIn("Not scored tonight: git fetch failed", pages["leaderboard/projects/o--broken.html"])
        self.assertIn("Every quality gate that applies is in place.", pages["leaderboard/projects/o--second.html"])
        self.assertEqual(
            json.loads(files["leaderboard/badges/o--first.json"]),
            {"schemaVersion": 1, "label": "project_validator", "message": "75% · Level 2", "color": "yellow"},
        )
        latest = json.loads(files["leaderboard/data/latest.json"])
        self.assertEqual([entry["name"] for entry in latest], ["o/first", "o/second", "o/broken"])

    def test_a_long_list_of_next_steps_is_cut(self) -> None:
        step = _step()
        with _directory() as data:
            with _directory() as results:
                write(_result("o/first", 1, 50, next_steps=[step] * 12), results)
                record(results, data, "2026-11-18")
            pages, _ = build(self.LISTED, data, "https://o.github.io/p/")
        page = pages["leaderboard/projects/o--first.html"]
        self.assertIn("| `coverage` | the project | FAIL | +1.0 |  |", page)
        self.assertIn("And 2 more.", page)

    def test_badges(self) -> None:
        self.assertEqual(badge(_result("o/r", 4, 100))["color"], "brightgreen")
        self.assertEqual(badge(_result("o/r", 0, 12.3))["message"], "12% · Level 0")
        self.assertEqual(badge(failed(EvaluationTests.ENTRY, "x", validator="v"))["message"], "error")

    def test_sparkline(self) -> None:
        self.assertEqual(sparkline([50]), "")
        self.assertIn('points="0.0,20.0 120.0,10.0 240.0,0.0"', sparkline([50, 75, 100]))
        self.assertIn('points="0.0,20.0 240.0,0.0"', sparkline([60, 120]))


class PreviewTests(unittest.TestCase):
    NEW = Entry(name="new/one", language="Rust", consent="https://github.com/new/one/issues/9")

    def _scored(self, entry: Entry) -> dict[str, object]:
        return _result(
            entry.name,
            1,
            50,
            next_steps=[_step(ecosystem="Rust", unit=".", tier="core", points=25), _step(check="license", points=12.5)],
        )

    def test_a_new_entry_is_previewed_with_its_score_and_next_steps(self) -> None:
        ok, preview = check([ENTRY], [ENTRY, self.NEW], lambda _: PUBLIC, self._scored)
        self.assertTrue(ok)
        self.assertTrue(preview.startswith(PREVIEW_MARKER + "\n## Leaderboard preview\n"))
        self.assertIn("### [new/one](https://github.com/new/one) on the Rust board", preview)
        self.assertIn("**50% · Level 1 Foundations**", preview)
        self.assertIn("- `coverage` (Rust): +25.0 points\n- `license`: +12.5 points\n", preview)
        self.assertNotIn("owner/repo", preview)

    def test_problems_fail_the_check_and_skip_the_evaluation(self) -> None:
        def never(_: Entry) -> dict[str, object]:
            raise AssertionError("evaluated")

        ok, preview = check([], [self.NEW], lambda _: Repository(found=False), never)
        self.assertFalse(ok)
        self.assertIn("Can not join yet:\n\n- https://github.com/new/one is not a public repository", preview)

    def test_a_duplicate_fails_and_an_unscored_entry_says_why(self) -> None:
        twice = [self.NEW, Entry(name="NEW/one", language="Go", consent=SEED)]
        ok, preview = check([], twice, lambda _: PUBLIC, lambda entry: failed(entry, "fetch failed", validator="v"))
        self.assertFalse(ok)
        self.assertIn("Listed more than once: new/one", preview)
        self.assertIn("Could not be scored: fetch failed", preview)

    def test_an_entry_without_next_steps_and_one_rounded_down(self) -> None:
        def complete(entry: Entry) -> dict[str, object]:
            return _result(entry.name, 3, 99.6)

        _, preview = check([], [self.NEW], lambda _: PUBLIC, complete)
        self.assertIn("**99% · Level 3 Hardening**\n\nScored by", preview)

    def test_nothing_changed(self) -> None:
        self.assertIn("No entry is added or changed.", check([ENTRY], [ENTRY], lambda _: PUBLIC, self._scored)[1])


class CommandTests(unittest.TestCase):
    def _run(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_matrix_lists_every_name(self) -> None:
        code, output, _ = self._run("matrix")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), [entry.name for entry in entries()])

    def test_record_adds_the_results(self) -> None:
        with _directory() as root:
            write(_result("o/r", 1, 50), root / "results")
            code, output, _ = self._run("record", str(root / "results"), str(root / "data"), "--date", "2026-11-18")
            self.assertEqual((code, output), (0, "o/r\n"))
            self.assertTrue((root / "data" / "history" / "o--r.jsonl").is_file())

    def test_a_broken_manifest_is_an_error(self) -> None:
        with _directory() as root:
            (root / "projects.toml").write_text("[[project]]\nname = 1\n")
            code, _, errors = self._run("--manifest", str(root / "projects.toml"), "matrix")
        self.assertEqual(code, 1)
        self.assertIn("leaderboard: ", errors)

    def _manifest(self, root: Path, origin: Path) -> Path:
        """A one-entry manifest whose checkout in `root / "cache"` fetches from `origin`."""
        (root / "projects.toml").write_text('[[project]]\nname = "o/r"\nlanguage = "Python"\nconsent = "seed"\n')
        (root / "cache" / "o--r").mkdir(parents=True)
        _git(root / "cache" / "o--r", "init", "--quiet")
        _git(root / "cache" / "o--r", "remote", "add", "origin", origin.as_uri())
        return root / "projects.toml"

    def test_evaluate_fetches_and_scores_each_project(self) -> None:
        with _directory() as root:
            origin = root / "origin"
            shutil.copytree(FIXTURES / "well_configured_python", origin)
            _git(origin, "init", "--quiet")
            _git(origin, "add", ".")
            _git(origin, "commit", "--quiet", "-m", "fixture")
            manifest = self._manifest(root, origin)
            code, _, _ = self._run(
                "--manifest", str(manifest), "evaluate", str(root / "out"), "o/r", "--cache", str(root / "cache")
            )
            result = json.loads((root / "out" / "o--r.json").read_text())
            self.assertEqual(result["commit"], _git(origin, "rev-parse", "HEAD"))
        self.assertEqual(code, 0)
        self.assertGreaterEqual(result["score"]["level"], 1)

    def test_check_writes_the_preview_and_fails_on_a_problem(self) -> None:
        with _directory() as root:
            (root / "projects.toml").write_text('[[project]]\nname = "o/r"\nlanguage = "Python"\nconsent = "no"\n')
            with mock.patch("leaderboard.__main__.github_repository", return_value=PUBLIC) as asked:
                code, output, _ = self._run(
                    *("--manifest", str(root / "projects.toml"), "check"),
                    *("--base", str(root / "missing.toml"), "--out", str(root / "out" / "preview.md")),
                )
            preview = (root / "out" / "preview.md").read_text()
        self.assertEqual(code, 1)
        self.assertEqual(output, preview + "\n")
        self.assertIn("`consent` must link", preview)
        asked.assert_called_once_with("o/r", mock.ANY)

    def test_evaluate_writes_an_unscored_result_for_a_project_that_can_not_be_fetched(self) -> None:
        with _directory() as root:
            (root / "projects.toml").write_text('[[project]]\nname = "o/r"\nlanguage = "Go"\nconsent = "seed"\n')
            (root / "cache" / "o--r").mkdir(parents=True)
            _git(root / "cache" / "o--r", "init", "--quiet")
            _git(root / "cache" / "o--r", "remote", "add", "origin", (root / "missing").as_uri())
            code, output, _ = self._run(
                "--manifest", str(root / "projects.toml"), "evaluate", str(root / "out"), "--cache", str(root / "cache")
            )
            self.assertEqual((code, output.strip()), (0, str(root / "out" / "o--r.json")))
            self.assertIn("git fetch failed", json.loads((root / "out" / "o--r.json").read_text())["error"])


def _workflow(name: str) -> Any:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(name: str) -> set[str]:
    workflow = _workflow(name)
    return set(workflow.get("on", workflow.get(True)))  # PyYAML reads the key `on` as True


class WorkflowTests(unittest.TestCase):
    def test_only_recording_writes_and_only_publishing_deploys(self) -> None:
        workflow = _workflow("leaderboard.yml")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(
            {name: job.get("permissions") for name, job in workflow["jobs"].items()},
            {
                "list": None,
                "evaluate": None,
                "record": {"contents": "write"},
                "publish": {"contents": "read", "pages": "write", "id-token": "write"},
            },
        )
        self.assertEqual(workflow["jobs"]["publish"]["uses"], "./.github/workflows/pages.yml")

    def test_it_runs_nightly_and_on_demand(self) -> None:
        self.assertEqual(_triggers("leaderboard.yml"), {"schedule", "workflow_dispatch"})

    def test_no_checkout_keeps_its_credentials(self) -> None:
        for name in ("leaderboard.yml", "leaderboard-check.yml", "pages.yml"):
            for job_name, job in _workflow(name)["jobs"].items():
                for step in job.get("steps", []):
                    if str(step.get("uses", "")).startswith("actions/checkout@"):
                        with self.subTest(workflow=name, job=job_name):
                            self.assertIs(step["with"]["persist-credentials"], False)

    def test_the_check_runs_the_pull_request_s_code_read_only_and_never_comments(self) -> None:
        self.assertEqual(_workflow("leaderboard-check.yml")["permissions"], {"contents": "read"})
        self.assertEqual(_triggers("leaderboard-check.yml"), {"pull_request"})
        (job,) = _workflow("leaderboard-check.yml")["jobs"].values()
        self.assertNotIn("permissions", job)
        script = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertNotRegex(script, r"\bgh (api|pr)\b")

    def test_the_comment_never_checks_out_or_runs_the_pull_request(self) -> None:
        workflow = _workflow("leaderboard-comment.yml")
        self.assertEqual(workflow["permissions"], {})
        (job,) = workflow["jobs"].values()
        self.assertEqual(job["permissions"], {"actions": "read", "pull-requests": "write"})
        self.assertFalse([step for step in job["steps"] if "checkout" in str(step.get("uses", ""))])
        script = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn("tr -cd '0-9'", script)
        self.assertIn('if [ "$head" != "$HEAD_SHA" ]', script)
        self.assertNotIn("GITHUB_ENV", script)
        self.assertIn(PREVIEW_MARKER, script)

    def test_the_site_is_built_with_the_leaderboard_data(self) -> None:
        self.assertIn("workflow_call", _triggers("pages.yml"))
        self.assertIn("--leaderboard", (WORKFLOWS / "pages.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
