from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.status_badges import CI_HINT, QUALITY_HINT, status_badges
from project_validator.core import Result, Status
from tests.support import FIXTURES, make_context, temp_project

CI_BADGE = "![ci](https://github.com/o/r/actions/workflows/ci.yml/badge.svg)"
QUALITY_BADGE = "![codecov](https://codecov.io/gh/o/r/graph/badge.svg)"


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return status_badges.run(make_context(root))


class StatusBadgesTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(status_badges.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = status_badges.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result, Result.passed("README.md shows CI (GitHub Actions) and quality (Codecov) badges"))

    def test_fails_without_a_readme_or_badges(self) -> None:
        self.assertEqual(_run({"docs/guide.md": CI_BADGE}), Result.failed("no README", CI_HINT, QUALITY_HINT))
        self.assertEqual(
            _run({"README.md": "# app\n"}), Result.failed("README.md shows no status badges", CI_HINT, QUALITY_HINT)
        )

    def test_warns_when_only_one_kind_of_badge_is_shown(self) -> None:
        self.assertEqual(
            _run({"README.md": CI_BADGE}),
            Result.warned("README.md shows a CI badge (GitHub Actions) but no quality badge", QUALITY_HINT),
        )
        self.assertEqual(
            _run({"README.md": QUALITY_BADGE}),
            Result.warned("README.md shows a quality badge (Codecov) but no CI badge", CI_HINT),
        )

    def test_recognises_the_badges_of_every_ci_provider(self) -> None:
        badges = {
            "GitHub Actions": "https://img.shields.io/github/actions/workflow/status/o/r/ci.yml",
            "GitLab CI": "https://gitlab.com/o/r/badges/main/pipeline.svg",
            "Azure Pipelines": "https://dev.azure.com/o/p/_apis/build/status/r",
            "AppVeyor": "https://ci.appveyor.com/api/projects/status/abc",
            "CircleCI": "https://dl.circleci.com/status-badge/img/gh/o/r/tree/main.svg",
            "Travis CI": "https://app.travis-ci.com/o/r.svg?branch=main",
            "Jenkins": "https://ci.example.com/buildStatus/icon?job=r",
            "Buildkite": "https://badge.buildkite.com/abc.svg",
            "Drone": "https://drone.example.com/api/badges/o/r/status.svg",
            "Cirrus CI": "https://api.cirrus-ci.com/github/o/r.svg",
            "Woodpecker": "https://ci.example.com/api/badges/42/status.svg",
        }
        for provider, url in badges.items():
            with self.subTest(provider):
                result = _run({"README.md": f"![build]({url}) {QUALITY_BADGE}"})
                self.assertEqual(result.message, f"README.md shows CI ({provider}) and quality (Codecov) badges")

    def test_recognises_quality_badges(self) -> None:
        badges = {
            "Codecov": "https://img.shields.io/codecov/c/github/o/r",
            "Coveralls": "https://coveralls.io/repos/github/o/r/badge.svg",
            "SonarCloud": "https://sonarcloud.io/api/project_badges/measure?project=r&metric=alert_status",
            "Codacy": "https://app.codacy.com/project/badge/Grade/abc",
            "Code Climate": "https://api.codeclimate.com/v1/badges/abc/maintainability",
            "DeepSource": "https://app.deepsource.com/gh/o/r.svg/?label=active+issues",
            "Coverity Scan": "https://scan.coverity.com/projects/42/badge.svg",
            "OpenSSF Scorecard": "https://api.scorecard.dev/projects/github.com/o/r/badge",
            "OpenSSF Best Practices": "https://www.bestpractices.dev/projects/42/badge",
        }
        for service, url in badges.items():
            with self.subTest(service):
                result = _run({"README.md": f"{CI_BADGE} ![quality]({url})"})
                self.assertEqual(result.message, f"README.md shows CI (GitHub Actions) and quality ({service}) badges")

    def test_the_readme_is_found_where_forges_look_for_it(self) -> None:
        for path in ("README.rst", "readme.md", "README", ".github/README.md", "docs/README.md"):
            with self.subTest(path):
                self.assertEqual(_run({path: f"{CI_BADGE}\n{QUALITY_BADGE}\n"}).status, Status.PASS)
