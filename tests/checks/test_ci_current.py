from __future__ import annotations

import os
import shutil
import unittest
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from project_validator.checks.ci_current import HISTORY_NOTE, REMOVE_HINT, ci_current
from project_validator.core import Result
from tests.support import make_context, temp_project
from tests.test_project import git

WORKFLOW = {
    ".github/workflows/ci.yml": "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n"
}
TRAVIS = {".travis.yml": "language: cpp\nscript: make\n"}
ORG_BADGE = "[![Build Status](https://travis-ci.org/o/r.png?branch=master)](https://travis-ci.org/o/r)\n"
COM_BADGE = "[![Build Status](https://app.travis-ci.com/o/r.svg?branch=master)](https://app.travis-ci.com/o/r)\n"


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return ci_current.run(make_context(root))


def _commit(root: Path, paths: list[str], date: str) -> None:
    """Commit `paths` as of `date` (ISO 8601)."""
    git(root, "add", *paths)
    environment = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    previous = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)
    try:
        git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", date)
    finally:
        for name, value in previous.items():
            if value is None:
                del os.environ[name]
            else:
                os.environ[name] = value


def _date(path: Path, date: str) -> None:
    """Set the file's modification time to `date` (ISO 8601)."""
    seconds = datetime.fromisoformat(date).timestamp()
    os.utime(path, (seconds, seconds))


def _run_with_history(files: Mapping[str, str], commits: list[tuple[list[str], str]]) -> Result:
    """Run on a git checkout of `files`, each group of paths committed as of its date, in order."""
    with temp_project(files) as root:
        git(root, "init", "-q")
        for paths, date in commits:
            _commit(root, paths, date)
        return ci_current.run(make_context(root))


class CiCurrentTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(ci_current.languages, frozenset())

    def test_is_skipped_without_ci(self) -> None:
        self.assertEqual(_run({"README.md": "# app\n"}), Result.skipped("no CI configuration"))

    def test_ci_without_git_history_passes_and_says_its_age_was_not_compared(self) -> None:
        self.assertEqual(
            _run({**WORKFLOW, **TRAVIS}), Result.passed("no CI configuration is known to be defunct", HISTORY_NOTE)
        )

    def test_one_provider_has_no_other_to_be_compared_with(self) -> None:
        """Ages are compared between providers, so a project with one needs no dates, whatever its files' times."""
        for spread in (False, True):
            with (
                self.subTest(spread=spread),
                temp_project({**WORKFLOW, ".github/workflows/old.yml": "on: push\n"}) as root,
            ):
                if spread:
                    _date(root / ".github/workflows/old.yml", "2015-01-01T00:00:00Z")
                result = ci_current.run(make_context(root))
            self.assertEqual(result, Result.passed("no CI configuration is known to be defunct"))

    def test_without_git_history_the_file_dates_tell_when_each_configuration_changed(self) -> None:
        """An unpacked copy that kept its file times (or a long-lived working copy) dates each file by its last write,
        never before its last commit."""
        with temp_project({**WORKFLOW, **TRAVIS}) as root:
            _date(root / ".travis.yml", "2018-10-20T14:50:08Z")
            _date(root / ".github/workflows/ci.yml", "2026-04-14T17:49:00Z")
            result = ci_current.run(make_context(root))
        self.assertEqual(
            result,
            Result.warned(
                "1 CI configuration looks unused: Travis CI",
                ".travis.yml: last modified 2018-10-20 (its file date), 7 years before GitHub Actions (2026-04-14)",
                REMOVE_HINT,
            ),
        )

    def test_file_dates_within_a_day_of_each_other_are_a_fresh_checkout_and_tell_nothing(self) -> None:
        with temp_project({**WORKFLOW, **TRAVIS}) as root:
            _date(root / ".travis.yml", "2026-04-14T00:00:00Z")
            _date(root / ".github/workflows/ci.yml", "2026-04-14T20:00:00Z")
            result = ci_current.run(make_context(root))
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct", HISTORY_NOTE))

    def test_a_travis_configuration_whose_badges_are_of_travis_ci_org_is_defunct(self) -> None:
        """travis-ci.org shut down in June 2021: a project whose README still shows its badges never moved to
        travis-ci.com, so its Travis CI configuration has not run since."""
        self.assertEqual(
            _run({**WORKFLOW, **TRAVIS, "README.md": f"# app\n{ORG_BADGE}"}),
            Result.failed(
                "1 CI configuration is defunct: Travis CI",
                ".travis.yml: README.md's Travis CI badge is of travis-ci.org, which shut down in June 2021",
                REMOVE_HINT,
                HISTORY_NOTE,
            ),
        )

    def test_a_travis_ci_com_badge_shows_the_project_moved(self) -> None:
        result = _run({**WORKFLOW, **TRAVIS, "README.md": f"# app\n{ORG_BADGE}{COM_BADGE}"})
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct", HISTORY_NOTE))


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class HistoryTests(unittest.TestCase):
    def test_a_ci_configuration_left_years_behind_another_looks_unused(self) -> None:
        result = _run_with_history(
            {**WORKFLOW, **TRAVIS}, [([".travis.yml"], "2018-10-20T14:50:08Z"), ([".github"], "2026-04-14T17:49:00Z")]
        )
        self.assertEqual(
            result,
            Result.warned(
                "1 CI configuration looks unused: Travis CI",
                ".travis.yml: last changed 2018-10-20, 7 years before GitHub Actions (2026-04-14)",
                REMOVE_HINT,
            ),
        )

    def test_the_newest_file_of_a_provider_is_when_it_last_changed(self) -> None:
        workflows = {**WORKFLOW, ".github/workflows/old.yml": WORKFLOW[".github/workflows/ci.yml"]}
        result = _run_with_history(
            {**workflows, **TRAVIS},
            [
                ([".github/workflows/old.yml"], "2015-01-01T00:00:00Z"),
                ([".travis.yml"], "2024-01-01T00:00:00Z"),
                ([".github/workflows/ci.yml"], "2025-06-01T00:00:00Z"),
            ],
        )
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct"))

    def test_two_years_apart_or_less_is_current(self) -> None:
        result = _run_with_history(
            {**WORKFLOW, **TRAVIS}, [([".travis.yml"], "2024-05-01T00:00:00Z"), ([".github"], "2026-04-30T00:00:00Z")]
        )
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct"))

    def test_a_lone_ci_configuration_is_never_unused_by_age(self) -> None:
        result = _run_with_history(TRAVIS, [([".travis.yml"], "2012-01-01T00:00:00Z")])
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct"))

    def test_certain_evidence_fails_even_when_the_history_also_shows_it(self) -> None:
        result = _run_with_history(
            {**WORKFLOW, **TRAVIS, "README.md": f"# app\n{ORG_BADGE}"},
            [([".travis.yml", "README.md"], "2018-10-20T00:00:00Z"), ([".github"], "2026-04-14T00:00:00Z")],
        )
        self.assertEqual(
            result,
            Result.failed(
                "1 CI configuration is defunct: Travis CI",
                ".travis.yml: README.md's Travis CI badge is of travis-ci.org, which shut down in June 2021",
                ".travis.yml: last changed 2018-10-20, 7 years before GitHub Actions (2026-04-14)",
                REMOVE_HINT,
            ),
        )

    def test_a_shallow_clone_has_no_history_to_compare(self) -> None:
        with temp_project({**WORKFLOW, **TRAVIS}) as source:
            git(source, "init", "-q")
            _commit(source, [".travis.yml"], "2018-01-01T00:00:00Z")
            _commit(source, [".github"], "2026-01-01T00:00:00Z")
            with temp_project({}) as parent:
                clone = parent / "clone"
                git(parent, "clone", "-q", "--depth", "1", f"file://{source}", str(clone))
                result = ci_current.run(make_context(clone))
        self.assertEqual(result, Result.passed("no CI configuration is known to be defunct", HISTORY_NOTE))


if __name__ == "__main__":
    unittest.main()
