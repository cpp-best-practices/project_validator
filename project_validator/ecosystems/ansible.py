"""Ansible: playbooks, roles and collections, a format recognised by content: a collection's `galaxy.yml`, a role's
`meta/main.yml` with `galaxy_info`, an `ansible.cfg`, a molecule scenario, or a playbook (YAML whose plays name
`hosts` and `tasks` or `roles`). Its files are YAML, the Data format's; its Jinja templates (`.j2`) belong to it
without being a format. What is asked of it is hygiene: ansible-lint lints it (`static-analysis`, and
`security-scanning` with its risky-command and no-log rules, beside checkov and KICS), and its tests run
(`tests-run`): molecule scenarios, or a collection's ansible-test integration targets.

Left for the checks they belong to: ansible-lint's `production` profile or `--strict` as warnings-as-errors (a format
has no compiler warnings), and the target platforms and ansible-core versions as a platform axis (a format has no
toolchain)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from project_validator.core import Context, Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.ecosystems.python import PYTHON_ONLY, PYTHON_TEST_FILES
from project_validator.facts import Command, Fact, Facts, Origin, Unknown, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, program
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Invocation, found_at
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, yaml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, combined, defined_by, starts, when
from project_validator.tools.misconfiguration import misconfiguration_scanner

ANSIBLE = "Ansible"
ANSIBLE_ONLY = frozenset({ANSIBLE})
# What the playbooks, roles and tests are written in.
YAML = frozenset({"YAML"})


# --- Recognition ----------------------------------------------------------------------------------------------------

_PROJECT_FILES = frozenset({"galaxy.yml", "galaxy.yaml", "ansible.cfg"})
_ROLE_META = re.compile(r"(?:^|/)meta/main\.ya?ml$")
_MOLECULE_SCENARIO = re.compile(r"(?:^|/)molecule/[^/]+/molecule\.ya?ml$")
# A play: a top-level list item naming its hosts, with tasks or roles to run on them.
_PLAY = re.compile(r"^-\s+(?:name|hosts):", re.MULTILINE)
_PLAY_HOSTS = re.compile(r"^(?:-\s+|\s+)hosts:", re.MULTILINE)
_PLAY_RUNS = re.compile(r"^\s+(?:tasks|roles|pre_tasks|post_tasks|handlers):", re.MULTILINE)


def _is_playbook(head: str) -> bool:
    return all(pattern.search(head) for pattern in (_PLAY, _PLAY_HOSTS, _PLAY_RUNS))


def ansible_project(project: Project) -> frozenset[str]:
    """Whether the project is Ansible's: a collection, a role, an `ansible.cfg`, a molecule scenario or a playbook."""
    for path in project.files():
        name = PurePosixPath(path).name
        if name in _PROJECT_FILES or _MOLECULE_SCENARIO.search(path):
            return ANSIBLE_ONLY
        if _ROLE_META.search(path) and "galaxy_info" in project.read_head(path):
            return ANSIBLE_ONLY
        if name.endswith((".yml", ".yaml")) and _is_playbook(project.read_head(path)):
            return ANSIBLE_ONLY
    return frozenset()


ANSIBLE_ECOSYSTEM = Ecosystem(
    label="Ansible",
    kind="format",
    languages=ANSIBLE_ONLY,
    # A role's Jinja templates (`templates/*.j2`) belong to it without being a format of their own.
    ambiguous_suffixes={".j2": None},
    detect=ansible_project,
    ci_programs=(
        ("ansible",),
        ("ansible-playbook",),
        ("ansible-galaxy",),
        ("ansible-lint",),
        ("ansible-test",),
        ("molecule",),
    ),
    ci_usage=re.compile(r"(?<![\w-])ansible-lint(?:-action)?\b"),
)


# --- Tests ----------------------------------------------------------------------------------------------------------

MOLECULE_SCENARIOS = TestFiles(
    name="molecule scenarios (molecule/*/molecule.yml)",
    languages=ANSIBLE_ONLY,
    path=_MOLECULE_SCENARIO,
    written_in=YAML,
)
ANSIBLE_TEST_TARGETS = TestFiles(
    name="ansible-test integration targets (tests/integration/targets/*/tasks/main.yml)",
    languages=ANSIBLE_ONLY,
    path=re.compile(r"(?:^|/)tests/integration/targets/[^/]+/tasks/main\.ya?ml$"),
    written_in=YAML,
)
MOLECULE = test_runner(
    name="molecule",
    languages=ANSIBLE_ONLY,
    how="molecule test",
    runs=when(starts(("molecule", "test")), tested),
    tests=tests_of(MOLECULE_SCENARIOS.name),
)


def _read_scenario(path: str, text: str) -> Iterator[Fact]:
    if _MOLECULE_SCENARIO.search(path):
        yield from yaml_settings("molecule", path, text, "verifier")


MOLECULE_SETTINGS = SettingsReader(name="molecule", files=("molecule.yml", "molecule.yaml"), read=_read_scenario)


def _testinfra(command: Command, facts: Facts) -> Run | None:
    """`molecule test` where a scenario's verifier is testinfra: it runs the scenario's `tests/test_*.py` with pytest
    against the instances it created."""
    if not starts(("molecule", "test"))(command):
        return None
    read = [setting for setting in facts.settings("molecule") if setting.key == "name" and setting.value == "testinfra"]
    return tested(read=read) if read else None


# The Python tests of a scenario with the testinfra verifier, which molecule runs (kubespray's roles).
TESTINFRA = test_runner(
    name="molecule's testinfra verifier",
    languages=PYTHON_ONLY,
    # Never suggested: a Python project is not told to adopt molecule.
    how="",
    runs=_testinfra,
    tests=tests_of(PYTHON_TEST_FILES.name),
    reads=("molecule",),
)
ANSIBLE_TEST = test_runner(
    name="ansible-test",
    languages=ANSIBLE_ONLY,
    how="ansible-test integration (in a collection)",
    runs=when(starts(("ansible-test", "integration"), ("ansible-test", "units")), tested),
    tests=tests_of(ANSIBLE_TEST_TARGETS.name),
)


# --- Lints and policy scanners --------------------------------------------------------------------------------------

ANSIBLE_LINT_SETTINGS = file_reader(
    "ansible-lint",
    (
        ".ansible-lint",
        ".ansible-lint.yml",
        ".ansible-lint.yaml",
        ".config/ansible-lint.yml",
        ".config/ansible-lint.yaml",
    ),
)
_ANSIBLE_LINT_RUNS = starts(("ansible-lint",))
# ansible-lint's rules include security ones: no shell for what a module does (risky-shell-pipe), no_log on secrets.
ANSIBLE_LINT = combined(
    analyzer(
        name="ansible-lint",
        languages=ANSIBLE_ONLY,
        how="ansible-lint (or ansible/ansible-lint)",
        analyses=when(_ANSIBLE_LINT_RUNS, analysed),
        rules=defined_by(files=(ANSIBLE_LINT_SETTINGS.name,)),
    ),
    scanner(
        name="ansible-lint",
        languages=ANSIBLE_ONLY,
        how="ansible-lint (its risky-* and no-log rules)",
        scans=when(_ANSIBLE_LINT_RUNS, scanned),
    ),
)
ANSIBLE_LINT_ACTION = Action(name="ansible/ansible-lint", runs=lambda _inputs: (("ansible-lint",),))
ANSIBLE_LINT_COMMUNITY_ACTION = Action(
    name="ansible-community/ansible-lint-action", runs=lambda _inputs: (("ansible-lint",),)
)
# Of the misconfiguration scanners, checkov and KICS read Ansible; trivy does not.
CHECKOV = misconfiguration_scanner("checkov", ANSIBLE_ONLY, "checkov -d . --framework ansible", starts(("checkov",)))
KICS = misconfiguration_scanner("KICS", ANSIBLE_ONLY, "kics scan -p .", starts(("kics", "scan")))


# --- antsibull-nox (#261) -------------------------------------------------------------------------------------------

# antsibull-nox, the CI driver of the ansible-collections organisation: `nox` runs the sessions `antsibull-nox.toml`
# configures (community.general runs them through antsibull-nox's reusable workflow).
ANTSIBULL_NOX_WORKFLOW = Action(
    name="ansible-community/antsibull-nox/.github/workflows/reusable-nox-matrix.yml", runs=lambda _inputs: (("nox",),)
)
_ANTSIBULL_NOX = ("antsibull-nox.toml",)
# A session and what it runs.
_SESSIONS = {
    "ansible_test_sanity": ("ansible-test", "sanity"),
    "ansible_test_units": ("ansible-test", "units"),
    "ansible_test_integration": ("ansible-test", "integration"),
    "ansible_lint": ("ansible-lint",),
}
# The lint session's switches (`run_ruff_check = true`) and what each runs.
_LINTS = {
    "run_ruff_check": ("ruff", "check", "."),
    "run_ruff_format": ("ruff", "format", "--check", "."),
    "run_black": ("black", "--check", "."),
    "run_isort": ("isort", "--check", "."),
    "run_flake8": ("flake8",),
    "run_pylint": ("pylint",),
    "run_yamllint": ("yamllint", "."),
    "run_mypy": ("mypy",),
}


def _lint_commands(path: str, lint: Mapping[str, object]) -> Iterator[Invocation]:
    for switch, argv in _LINTS.items():
        if lint.get(switch) is True:
            configured = lint.get("mypy_config") if switch == "run_mypy" else None
            words = (*argv, "--config-file", configured) if isinstance(configured, str) else argv
            line = f"antsibull-nox's lint session ({switch})"
            yield Invocation(argv=words, line=line, origin=Origin(path=path, at=("sessions", "lint", switch)))


def _antsibull_nox_sessions(command: Command, context: Context) -> list[Expansion] | None:
    """The sessions `nox` runs, as `antsibull-nox.toml` configures them: those `-e`/`-s` names, or all of them."""
    argv = resolved(command)
    if program(argv) != "nox" or (path := found_at(context, command.directory, _ANTSIBULL_NOX)) is None:
        return None
    try:
        sessions = tomllib.loads(context.project.read_text(path)).get("sessions", {})
    except tomllib.TOMLDecodeError as error:
        subject = f"the antsibull-nox configuration {path}"
        return [Unknown(origin=Origin(path=path), subject=subject, reason=str(error), hides="commands")]
    named = {name.replace("-", "_") for name in option_values(argv, "-e", "-s", "--session", "--sessions")}
    chosen = {name: value for name, value in sessions.items() if not named or any(name in found for found in named)}
    found: list[Expansion] = [
        Invocation(
            argv=_SESSIONS[name],
            line=f"antsibull-nox's {name} session",
            origin=Origin(path=path, at=("sessions", name)),
        )
        for name in chosen
        if name in _SESSIONS
    ]
    if isinstance(lint := chosen.get("lint"), Mapping):
        found.extend(_lint_commands(path, lint))
    return found or None


ANTSIBULL_NOX = CommandExpander(name="antsibull-nox sessions", expand=_antsibull_nox_sessions)
