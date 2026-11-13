"""GitHub Action repositories: a repository whose product is a reusable action (`action.yml` or `action.yaml` at its
root), a format recognised by content. The action's definition is YAML, the Data format's, and a JavaScript or Docker
action's code is judged by its own profile. What is asked of the repository is that a workflow of its own uses the
action (`uses: ./`), the self-test that is its `tests-run`; that actionlint lints its workflows (`static-analysis`);
and that zizmor audits them and the action (`security-scanning`). Every repository's workflows get `ci-lint` and
`action-pinning` already; this profile asks more of one whose product is an action.

Left for the checks they belong to: every `uses:` pinned to a commit with no tag allowance (`action-pinning`),
`action.yml`'s name, description, branding and `runs.using` on a supported runtime (`packaging`, #30), and a
self-test on more than one OS (a platform axis, which a format has no toolchain to carry)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

GITHUB_ACTION = "GitHub Action"
GITHUB_ACTION_ONLY = frozenset({GITHUB_ACTION})
YAML = frozenset({"YAML"})
ACTION_FILES = ("action.yml", "action.yaml")


def action_repository(project: Project) -> frozenset[str]:
    """Whether the repository's product is an action: its definition at the root (one in a subdirectory is a local
    action of the repository's own workflows)."""
    return GITHUB_ACTION_ONLY if any(project.exists(name) for name in ACTION_FILES) else frozenset()


GITHUB_ACTION_ECOSYSTEM = Ecosystem(
    label="GitHub Action",
    kind="format",
    languages=GITHUB_ACTION_ONLY,
    detect=action_repository,
    # actionlint and zizmor are every repository's hygiene (`ci-lint`), so running them shows no job to be the
    # action's: nothing in CI does, and a lint job of a C++ project stays that project's.
)


# --- The self-test: a workflow of the repository uses the action -----------------------------------------------------

# The step `uses: ./` runs the action from the checkout; a path below (`./.github/actions/x`) is a local action.
_USES_ITSELF = re.compile(r"^\s*-?\s*uses:\s*['\"]?\./['\"]?\s*(?:#.*)?$", re.MULTILINE)
# What the step is expanded into, so that the test runner can claim it: a workflow's `uses: ./` is not a command.
USES_ITSELF = "uses-the-action-itself"

SELF_TESTS = TestFiles(
    name="workflows that use the action itself (uses: ./)",
    languages=GITHUB_ACTION_ONLY,
    path=re.compile(r"^\.github/workflows/.+\.ya?ml$"),
    contains=_USES_ITSELF,
    written_in=YAML,
)
SELF_TEST = test_runner(
    name="the action's own workflow",
    languages=GITHUB_ACTION_ONLY,
    how="a workflow step `uses: ./`, which runs the action from the checkout",
    runs=when(starts((USES_ITSELF,)), tested),
    tests=tests_of(SELF_TESTS.name),
)
USES_ITSELF_ACTION = Action(name="./", runs=lambda _inputs: ((USES_ITSELF,),))


# --- Linting and auditing the workflows and the action ---------------------------------------------------------------

ACTIONLINT_SETTINGS = file_reader("actionlint", (".github/actionlint.yaml", ".github/actionlint.yml"))
ACTIONLINT = analyzer(
    name="actionlint",
    languages=GITHUB_ACTION_ONLY,
    how="actionlint (or rhysd/actionlint)",
    analyses=when(starts(("actionlint",)), analysed),
    rules=defined_by(files=(ACTIONLINT_SETTINGS.name,)),
)
ACTIONLINT_ACTION = Action(name="rhysd/actionlint", runs=lambda _inputs: (("actionlint",),))
ZIZMOR_SETTINGS = file_reader("zizmor", ("zizmor.yml", ".github/zizmor.yml"))
# zizmor audits the workflows and the action's definition for template injection, unpinned uses and the like.
ZIZMOR = scanner(
    name="zizmor",
    languages=GITHUB_ACTION_ONLY,
    how="zizmor . (or zizmorcore/zizmor-action)",
    scans=when(starts(("zizmor",)), scanned),
    reads=(ZIZMOR_SETTINGS.name,),
)


def _zizmor_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    return (("zizmor", *inputs.get("inputs", ".").split()),)


ZIZMOR_ACTION = Action(name="zizmorcore/zizmor-action", runs=_zizmor_action)
WOODRUFFW_ZIZMOR_ACTION = Action(name="woodruffw/zizmor-action", runs=_zizmor_action)
