from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.action_pinning import action_pinning
from project_validator.core import Context, Options, Project, Result, Status
from project_validator.policy.pinning import HINT
from project_validator.questions.pinning import BRANCH, SHORT, TAG, UNPINNED, pinning
from tests.support import CI_FILES, FIXTURES, GITHUB_WORKFLOW, make_context, temp_project

COMMIT = "11d5960a326750d5838078e36cf38b85af677262"


def _workflow(*references: str) -> str:
    steps = "".join(f"      - uses: {reference}\n" for reference in references)
    return f"jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n{steps}"


def _run(files: Mapping[str, str], *, allow_official_tags: bool = False) -> Result:
    with temp_project(files) as root:
        options = Options(allow_official_tags=allow_official_tags)
        return action_pinning.run(Context(Project(root), make_context(root).providers, options))


class PinningTests(unittest.TestCase):
    def test_classifies_how_a_reference_is_pinned(self) -> None:
        cases = {
            f"actions/checkout@{COMMIT}": None,
            "./.github/actions/setup": None,
            "docker://alpine@sha256:0123abcd": None,
            "docker://alpine:3.20": TAG,
            "actions/checkout@v4": TAG,
            "actions/checkout@v4.2.2": TAG,
            "rhysd/actionlint@1.7.12": TAG,
            "owner/action@v2-beta": TAG,
            "actions/checkout@11d5960": SHORT,
            "dtolnay/rust-toolchain@stable": BRANCH,
            "owner/action@main": BRANCH,
            "owner/action@release/v1": BRANCH,
            "owner/action": UNPINNED,
            "owner/action@": UNPINNED,
        }
        for reference, expected in cases.items():
            with self.subTest(reference):
                self.assertEqual(pinning(reference), expected)

    def test_official_actions_may_be_pinned_to_tags_when_allowed(self) -> None:
        """The allowance is the policy's: the reference is still classified as pinned to a tag."""
        official = {GITHUB_WORKFLOW: _workflow("actions/checkout@v4", "github/codeql-action/init@v3")}
        self.assertEqual(_run(official).status, Status.WARN)
        self.assertEqual(_run(official, allow_official_tags=True).status, Status.PASS)
        third_party = {GITHUB_WORKFLOW: _workflow("codecov/codecov-action@v5")}
        self.assertEqual(_run(third_party, allow_official_tags=True).status, Status.WARN)
        branch = {GITHUB_WORKFLOW: _workflow("actions/checkout@main")}
        self.assertEqual(_run(branch, allow_official_tags=True).status, Status.FAIL)


class ActionPinningTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(action_pinning.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = action_pinning.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result, Result.passed("all 7 actions are pinned to a commit"))

    def test_is_skipped_without_a_ci_provider_that_has_reusable_steps(self) -> None:
        for files in ({}, {".gitlab-ci.yml": "test:\n  script: make\n"}, {CI_FILES["Jenkins"]: ""}):
            with self.subTest(files=list(files)):
                self.assertEqual(
                    _run(files), Result(status=Status.SKIP, message="no CI configuration with reusable steps")
                )

    def test_passes_when_ci_uses_only_local_actions(self) -> None:
        result = _run({GITHUB_WORKFLOW: _workflow("./.github/actions/setup"), ".gitlab-ci.yml": "t:\n  script: make\n"})
        self.assertEqual(result, Result.passed("CI uses no actions from other repositories"))

    def test_warns_listing_the_actions_pinned_to_tags(self) -> None:
        result = _run(
            {GITHUB_WORKFLOW: _workflow(f"actions/checkout@{COMMIT}", "actions/setup-python@v5", "x/y@abc1234")}
        )
        self.assertEqual(
            result,
            Result.warned(
                "2 of 3 actions are pinned to a tag rather than a commit",
                f"{GITHUB_WORKFLOW}: actions/setup-python@v5 (pinned to a tag)",
                f"{GITHUB_WORKFLOW}: x/y@abc1234 (pinned to an abbreviated commit)",
                HINT,
            ),
        )
        self.assertEqual(
            _run({GITHUB_WORKFLOW: _workflow("actions/setup-python@v5")}, allow_official_tags=True).status, Status.PASS
        )

    def test_fails_when_an_action_follows_a_branch(self) -> None:
        workflow = _workflow("actions/checkout@v4", "dtolnay/rust-toolchain@stable", "actions/checkout@v4")
        result = _run(
            {
                GITHUB_WORKFLOW: workflow,
                ".github/workflows/release.yml": "jobs:\n  r:\n    uses: o/r/.github/workflows/r.yml\n",
            }
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.message, "3 of 3 actions are not pinned to a commit")
        self.assertEqual(
            result.details[:3],
            (
                f"{GITHUB_WORKFLOW}: actions/checkout@v4 (pinned to a tag)",
                f"{GITHUB_WORKFLOW}: dtolnay/rust-toolchain@stable (pinned to a branch)",
                ".github/workflows/release.yml: o/r/.github/workflows/r.yml (not pinned)",
            ),
        )

    def test_a_workflow_that_does_not_parse_is_left_to_data_wellformed(self) -> None:
        files = {GITHUB_WORKFLOW: "jobs: [\n", ".github/workflows/b.yml": _workflow(f"a/b@{COMMIT}")}
        self.assertEqual(_run(files), Result.passed("1 action is pinned to a commit"))
