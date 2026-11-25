"""A local check script or task, read as the pipeline of a project without CI (upstream #384).

A project that can't use CI may still run its tooling on demand: a `check.sh`, `make check`, `just check`, a
package's `check` script, or pre-commit's hooks. Without any CI configuration, each of these found (or the script
`--local-checks` names) is read as a job that runs it, so what it runs counts as CI's would. The project is judged
at an entry level: the checks only CI can satisfy (see `Check.ci_only`) warn instead of failing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.ci import CiFile, CiProvider, Load
from project_validator.core import Project
from project_validator.facts import CiJob, Fact, Origin
from project_validator.facts.expansion import script_facts

# Scripts named for checking, by where they are looked for.
SCRIPTS = tuple(
    f"{directory}check{suffix}"
    for directory in ("", "scripts/", "tools/", "bin/")
    for suffix in (".sh", "", ".ps1", ".py")
)
# A make or just target named `check`.
_TARGET = re.compile(r"^check\s*:(?!=)", re.MULTILINE)
TARGETS = {"Makefile": "make check", "GNUmakefile": "make check", "makefile": "make check", "justfile": "just check"}
TARGETS |= {"Justfile": "just check", ".justfile": "just check"}
# A package manifest's `check` script.
PACKAGE_SCRIPTS = {"package.json": "npm run check", "composer.json": "composer check"}
PRE_COMMIT = ".pre-commit-config.yaml"
_INTERPRETERS = {".sh": "sh {}", ".ps1": "pwsh -File {}", ".py": "python {}", "": "./{}"}
# What the project is judged at, said by each check only CI could satisfy.
ENTRY_LEVEL = "there is no CI: the local checks are read as the pipeline, and the project is judged at an entry level"


def entry_command(path: str) -> str:
    """How the entry point at `path` is run: `make check`, `npm run check`, `sh scripts/check.sh`."""
    name = PurePosixPath(path).name
    if name in TARGETS:
        return TARGETS[name]
    if name in PACKAGE_SCRIPTS:
        return PACKAGE_SCRIPTS[name]
    if name == PRE_COMMIT:
        return "pre-commit run --all-files"
    return _INTERPRETERS.get(PurePosixPath(path).suffix, "./{}").format(path)


def _has_check_script(project: Project, path: str) -> bool:
    try:
        scripts = json.loads(project.read_text(path)).get("scripts")
    except (ValueError, AttributeError):
        return False
    return isinstance(scripts, dict) and "check" in scripts


def _entry_points(project: Project) -> Iterator[str]:
    yield from (path for path in SCRIPTS if project.exists(path))
    yield from (path for path in TARGETS if project.exists(path) and _TARGET.search(project.read_text(path)))
    yield from (path for path in PACKAGE_SCRIPTS if project.exists(path) and _has_check_script(project, path))
    if project.exists(PRE_COMMIT):
        yield PRE_COMMIT


def _facts(path: str, document: object, load: Load) -> Iterator[Fact]:
    """One job that runs the entry point, on the machine it is run on."""
    del document, load
    origin = Origin(path=path)
    identity = f"local checks: {entry_command(path)}"
    yield CiJob(origin=origin, id=identity, provider=LOCAL_CHECKS.name, name=identity, os="unknown")
    yield from script_facts(entry_command(path), job=identity, origin=origin)


# Never found by its files, as other providers are: `local_check_files` finds it when there is no CI.
LOCAL_CHECKS = CiProvider(name="local checks", facts=_facts, parse=lambda text: text)


def local_check_files(project: Project, named: str | None = None) -> tuple[CiFile, ...]:
    """The entry points read as the pipeline: the one `named`, else each found."""
    found = [named] if named is not None else list(_entry_points(project))
    return tuple(CiFile(provider=LOCAL_CHECKS, path=path) for path in found)


__all__ = ["ENTRY_LEVEL", "LOCAL_CHECKS", "entry_command", "local_check_files"]
