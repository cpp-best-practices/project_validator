import unittest
from collections.abc import Mapping

from project_validator.checks.ci_lint import ci_lint
from project_validator.core import Result, Status
from tests.support import CI_FILES, FIXTURES, GITHUB_WORKFLOW, make_context, temp_project

GITHUB_HINT = "GitHub Actions: run actionlint (rhysd/actionlint) or zizmor (zizmorcore/zizmor-action) in CI"


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return ci_lint.run(make_context(root))


class CiLintTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(ci_lint.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = ci_lint.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result, Result.passed("CI lints its configuration (GitHub Actions: actionlint, zizmor)"))

    def test_is_skipped_without_ci(self) -> None:
        self.assertEqual(_run({}), Result(status=Status.SKIP, message="no CI configuration"))

    def test_is_skipped_when_no_linter_is_known_for_the_providers(self) -> None:
        result = _run({CI_FILES["Jenkins"]: "actionlint", CI_FILES["Drone"]: ""})
        self.assertEqual(
            result, Result(status=Status.SKIP, message="no configuration linter is known for Jenkins, Drone")
        )

    def test_each_provider_has_its_linters(self) -> None:
        cases = {
            "GitHub Actions": ("- uses: rhysd/actionlint@v1", "actionlint"),
            "GitLab CI": ("lint:\n  script: glab ci lint\n", "glab ci lint"),
            "CircleCI": ("steps:\n  - run: circleci config validate\n", "circleci config validate"),
        }
        for provider, (text, linter) in cases.items():
            with self.subTest(provider):
                result = _run({CI_FILES[provider]: text})
                self.assertEqual(result, Result.passed(f"CI lints its configuration ({provider}: {linter})"))

    def test_gitlab_configuration_can_be_linted_by_other_means(self) -> None:
        for text in ("gitlab-ci-local --preview > /dev/null", "curl $CI_API/api/v4/projects/42/ci/lint"):
            with self.subTest(text=text):
                self.assertEqual(_run({".gitlab-ci.yml": f"lint:\n  script: {text}\n"}).status, Status.PASS)

    def test_a_pre_commit_hook_counts(self) -> None:
        hooks = "repos:\n  - repo: https://github.com/woodruffw/zizmor-pre-commit\n    hooks:\n      - id: zizmor\n"
        result = _run({GITHUB_WORKFLOW: "jobs: {}\n", ".pre-commit-config.yaml": hooks})
        self.assertEqual(result, Result.passed("CI lints its configuration (GitHub Actions: zizmor)"))

    def test_warns_naming_each_provider_left_unlinted(self) -> None:
        self.assertEqual(
            _run({GITHUB_WORKFLOW: "jobs: {}\n"}),
            Result.warned("CI does not lint its GitHub Actions configuration", GITHUB_HINT),
        )
        result = _run({GITHUB_WORKFLOW: "run: actionlint\n", ".gitlab-ci.yml": "", CI_FILES["Jenkins"]: ""})
        self.assertEqual(
            result,
            Result.warned(
                "CI does not lint its GitLab CI configuration",
                "GitLab CI: run glab ci lint (or gitlab-ci-local --preview) in CI",
            ),
        )
