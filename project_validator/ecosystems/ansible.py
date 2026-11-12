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
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import combined, defined_by, starts, when
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
