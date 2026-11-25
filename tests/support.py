"""Helpers for building throw-away projects and contexts in tests."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

from project_validator.core import Check, Context, Options, Project, Result
from project_validator.ecosystems import BUILT_IN, C_FAMILY, Ecosystem, ecosystems_for, registered
from project_validator.ecosystems.c import C
from project_validator.ecosystems.cpp import CXX
from project_validator.facts import Command, Facts, Origin, resolved
from project_validator.facts.expansion import script_facts
from project_validator.facts.jobs import Job
from project_validator.judging import by_ecosystem
from project_validator.plugins import discover
from project_validator.views import console as console_view
from tests import layouts
from tests.layouts.model import ProjectLayout

FIXTURES = Path(__file__).parent / "fixtures"

# A format ecosystem that is not built in, for tests of the model: its files are data, not programs.
FORMAT_ECOSYSTEM = Ecosystem(
    label="Widget data", kind="format", languages=frozenset({"WDATA"}), source_suffixes={".wdata": "WDATA"}
)

requires_rich = unittest.skipUnless(console_view.available(), "rich is not installed")

NO_FILES: Mapping[str, str] = MappingProxyType({})


@contextmanager
def temp_project(files: Mapping[str, str]) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, contents in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(contents), encoding="utf-8")
        yield root


_FIXTURE_CONTEXTS: dict[tuple[Path, Options, tuple[str, ...], tuple[str, ...]], Context] = {}


def make_context(
    root: Path, options: Options | None = None, *, auxiliary: tuple[str, ...] = (), primary: tuple[str, ...] = ()
) -> Context:
    """A context for the project at `root`. The fixtures never change while the tests run, so a fixture's context (and
    the facts it extracts once) is shared by every test that asks for it the same way; a temporary project's is not."""
    options = options or Options()
    key = (root, options, auxiliary, primary)
    project = Project(root, auxiliary=auxiliary, primary=primary)
    if not root.is_relative_to(FIXTURES):
        return Context(project, discover().providers, options)
    if key not in _FIXTURE_CONTEXTS:
        _FIXTURE_CONTEXTS[key] = Context(project, discover().providers, options)
    return _FIXTURE_CONTEXTS[key]


def fixture_files(name: str) -> dict[str, str]:
    directory = FIXTURES / name
    return {
        path.relative_to(directory).as_posix(): path.read_text(encoding="utf-8")
        for path in directory.rglob("*")
        if path.is_file()
    }


PROJECT_LAYOUTS = (*layouts.PROFILE_LAYOUTS, layouts.UNRECOGNISED)


def checked_ecosystems(selected: Check, layout: ProjectLayout) -> tuple[Ecosystem, ...]:
    """The ecosystems `selected` judges in a project of `layout` (of its languages, and of its formats)."""
    supported = (ecosystem for ecosystem in BUILT_IN if ecosystem.languages <= selected.languages)
    return ecosystems_for(layout.languages | layout.formats, supported)


def layouts_checked_as(selected: Check, *ecosystems: Ecosystem) -> tuple[ProjectLayout, ...]:
    """Every layout in which `selected` judges exactly `ecosystems`."""
    return tuple(layout for layout in PROJECT_LAYOUTS if checked_ecosystems(selected, layout) == ecosystems)


def c_family_layouts(selected: Check) -> tuple[ProjectLayout, ...]:
    """The layouts in which `selected` judges only C, or only C++."""
    return (*layouts_checked_as(selected, C), *layouts_checked_as(selected, CXX))


def c_family_layouts_built_with(selected: Check, build_system: str) -> tuple[ProjectLayout, ...]:
    """The layouts in which `selected` judges only C or only C++, by the rules of `build_system`.

    A layout without a C or C++ build system is judged as a CMake project.
    """
    return tuple(
        layout
        for layout in c_family_layouts(selected)
        if CXX.used_build_systems(layout.build_systems)[0].name == build_system
    )


C_FAMILY_LAYOUTS = tuple(layout for layout in PROJECT_LAYOUTS if layout.gets_c_family_checks)
C_FAMILY_ONLY_LAYOUTS = tuple(layout for layout in C_FAMILY_LAYOUTS if layout.languages <= C_FAMILY)
OTHER_LANGUAGE_LAYOUTS = tuple(
    layout for layout in PROJECT_LAYOUTS if layout.languages and not layout.gets_c_family_checks
)
UNRECOGNISED_LAYOUTS = tuple(layout for layout in PROJECT_LAYOUTS if not (layout.languages or layout.formats))
NON_CMAKE_C_FAMILY_LAYOUTS = tuple(layout for layout in C_FAMILY_LAYOUTS if not layout.uses_cmake)


def _first_config_file(files: tuple[str, ...], directories: tuple[str, ...]) -> str:
    return files[0] if files else f"{directories[0]}/ci.yml"


# CI provider name -> a path its configuration is found at.
# Providers recognised by their configuration's content too (pre-commit.ci's `ci:` section) are tested on their own.
CI_FILES = {
    provider.name: _first_config_file(provider.files, provider.directories)
    for provider in discover().providers
    if (provider.files or provider.directories) and provider.recognises is None
}


@contextmanager
def layout_project(
    test: unittest.TestCase, layout: ProjectLayout, files: Mapping[str, str] = NO_FILES, **sub_test: object
) -> Iterator[Path]:
    """A sub-test on a project of `layout` with `files` added; `files` win over the layout's own files."""
    with test.subTest(layout=layout.name, **sub_test), temp_project({**layout.files, **files}) as root:
        yield root


def run_in_every_layout(
    test: unittest.TestCase,
    selected: Check,
    files: Mapping[str, str],
    layouts: tuple[ProjectLayout, ...] | None = None,
    options: Options | None = None,
    auxiliary: tuple[str, ...] = (),
) -> Result:
    """The result of `selected` in a project of each layout with `files` added, which must not depend on the layout.

    By default the layouts are every one in which `selected` judges only C, or only C++.
    """
    if layouts is None:
        layouts = c_family_layouts(selected)
    results: dict[str, Result] = {}
    # A format some layout's own files bring (a CMake layout's CMake code) is no layout's subject, in any of them.
    brought = frozenset().union(*(_brought_formats(layout) for layout in layouts))
    for layout in layouts:
        with temp_project({**layout.files, **files}) as root:
            result = selected.run(make_context(root, options, auxiliary=auxiliary))
        results[layout.name] = _without_formats(result, brought)
    expected = results[layouts[0].name]
    for name, result in results.items():
        with test.subTest(layout=name):
            test.assertEqual(result, expected)
    return expected


_BROUGHT: dict[str, frozenset[str]] = {}


def _brought_formats(layout: ProjectLayout) -> frozenset[str]:
    """The labels of the format ecosystems a layout's own files bring beside what it is about (a CMake layout's
    CMakeLists.txt is CMake code), which its tests are not about."""
    if layout.name not in _BROUGHT:
        with temp_project(layout.files) as root:
            found = make_context(root).structure.formats - layout.formats
        _BROUGHT[layout.name] = frozenset(
            ecosystem.label for ecosystem in registered() if ecosystem.kind == "format" and ecosystem.languages & found
        )
    return _BROUGHT[layout.name]


def _without_formats(result: Result, labels: frozenset[str]) -> Result:
    """`result` without the places of the format ecosystems `labels` names, refolded as the check folds its
    ecosystems; as it is when it has none of them, or a place of another unit."""
    if not labels or not any(place.ecosystem in labels for place in result.places):
        return result
    kept = [place for place in result.places if place.ecosystem not in labels]
    by_label = {place.ecosystem: place.result for place in kept}
    if len(by_label) != len(kept):
        return result
    ecosystems = {ecosystem.label: ecosystem for ecosystem in registered()}
    return by_ecosystem({ecosystems[label]: found for label, found in by_label.items()})


WELL_CONFIGURED = fixture_files("well_configured_cpp")
BARE_PROJECT = fixture_files("bare_cpp")


def well_configured(layout: ProjectLayout) -> dict[str, str]:
    """The files of the project of `layout`'s profile that passes every check that applies to it."""
    return fixture_files(f"well_configured_{layout.profile}")


# Projects that pass every check that applies to their language.
WELL_CONFIGURED_PYTHON = fixture_files("well_configured_python")
WELL_CONFIGURED_RUST = fixture_files("well_configured_rust")
WELL_CONFIGURED_GO = fixture_files("well_configured_go")
WELL_CONFIGURED_JAVASCRIPT = fixture_files("well_configured_javascript")
WELL_CONFIGURED_JVM = fixture_files("well_configured_jvm")
WELL_CONFIGURED_DOTNET = fixture_files("well_configured_dotnet")
WELL_CONFIGURED_PHP = fixture_files("well_configured_php")
WELL_CONFIGURED_RUBY = fixture_files("well_configured_ruby")
WELL_CONFIGURED_SWIFT = fixture_files("well_configured_swift")

# The providers whose configuration is not parsed, only scanned heuristically.
UNSTRUCTURED_CI_FILES = {
    provider.name: CI_FILES[provider.name]
    for provider in discover().providers
    if provider.name in CI_FILES and provider.facts is None
}
GITHUB_WORKFLOW = ".github/workflows/ci.yml"


def run_as(
    test: unittest.TestCase,
    selected: Check,
    files: dict[str, str],
    *ecosystems: Ecosystem,
    options: Options | None = None,
    auxiliary: tuple[str, ...] = (),
) -> Result:
    """The result of `selected` in every layout it judges as exactly `ecosystems`; it must not depend on the layout."""
    layouts = layouts_checked_as(selected, *ecosystems)
    test.assertTrue(layouts, f"no layout is judged as {[ecosystem.label for ecosystem in ecosystems]}")
    return run_in_every_layout(test, selected, files, layouts, options, auxiliary)


def run_in_layout(test: unittest.TestCase, name: str, selected: Check, files: Mapping[str, str]) -> Result:
    """The result of `selected` in a project of the layout called `name` with `files` added."""
    layouts = tuple(layout for layout in PROJECT_LAYOUTS if layout.name == name)
    test.assertTrue(layouts, f"no layout is called {name}")
    return run_in_every_layout(test, selected, files, layouts)


def command(line: str, env: Mapping[str, str] = NO_FILES) -> Command:
    """The command `line` as a CI job would run it, with `env` as its environment."""
    [found] = (
        fact
        for fact in script_facts(line, job="job", origin=Origin(path="ci.yml"), env=env)
        if isinstance(fact, Command)
    )
    return found


def evidence(*lines: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """What a CI job shows, as `platforms` reads it: `lines` as its texts, and the commands each line runs as a shell
    script (a line that is not a script, `uses: setup-go@v5`, runs nothing a toolchain claims)."""
    commands = tuple(
        resolved(fact)
        for line in lines
        for fact in script_facts(line, job="job", origin=Origin(path="ci.yml"))
        if isinstance(fact, Command)
    )
    return lines, commands


def uses(ecosystem: Ecosystem, *lines: str) -> bool:
    """Whether a CI job showing `lines` builds with `ecosystem` (see `Ecosystem.used_by`)."""
    return ecosystem.used_by(*evidence(*lines))


def config_facts(path: str, document: object, **files: str) -> Facts:
    """The facts of a project of a configuration file at `path` (`document`, written as JSON, which YAML reads) and
    `files`."""
    with temp_project({path: json.dumps(document), **files}) as root:
        return make_context(root).facts


def argvs(facts: Facts) -> list[tuple[str, ...]]:
    """The arguments of each command the facts hold, in order."""
    return [found.argv for found in facts.of(Command)]


def ci_jobs(files: Mapping[str, str]) -> tuple[Job, ...]:
    """The CI jobs a project with `files` has, as the checks see them."""
    with temp_project(files) as root:
        return make_context(root).ci_analysis.jobs


def checks_named(*names: str) -> tuple[Check, ...]:
    """The checks called `names`, in that order."""
    found = {found.name: found for found in discover().checks}
    return tuple(found[name] for name in names)


def github_job(runs_on: str, *steps: str, matrix: Mapping[str, object] | None = None) -> dict[str, str]:
    job: dict[str, object] = {"runs-on": runs_on, "steps": [{"run": step} for step in steps]}
    if matrix is not None:
        job["strategy"] = {"matrix": matrix}
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": job}})}


def github_action(uses: str, **inputs: str) -> dict[str, str]:
    """A GitHub workflow whose one job uses the action `uses` with `inputs`."""
    steps = [{"uses": uses, "with": inputs}]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": steps}}})}


def github_steps(*steps: str) -> dict[str, str]:
    """A GitHub workflow whose one job runs `steps`, each written `run: command` or `uses: action`."""
    parsed = [dict([step.split(": ", 1)]) for step in steps]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": parsed}}})}


def ci_running(provider: str, *commands: str) -> dict[str, str]:
    """A CI configuration of `provider` (see `CI_FILES`) with a job that runs `commands`."""
    if provider == "GitHub Actions":
        return github_job("ubuntu-latest", *commands)
    if provider == "GitLab CI":
        return {CI_FILES[provider]: json.dumps({"test": {"script": list(commands)}})}
    if provider == "Read the Docs":
        return {CI_FILES[provider]: json.dumps({"version": 2, "build": {"commands": list(commands)}})}
    if provider == "Google Cloud Build":
        steps = [{"name": "ubuntu", "args": ["bash", "-c", command]} for command in commands]
        return {CI_FILES[provider]: json.dumps({"steps": steps})}
    if provider == "AppVeyor":
        return {CI_FILES[provider]: json.dumps({"image": "Ubuntu2204", "build": "off", "test_script": list(commands)})}
    if provider == "Azure Pipelines":
        return {CI_FILES[provider]: json.dumps({"steps": [{"script": command} for command in commands]})}
    if provider == "CircleCI":
        steps = [{"run": command} for command in commands]
        return {CI_FILES[provider]: json.dumps({"jobs": {"test": {"docker": [{"image": "x"}], "steps": steps}}})}
    if provider == "Travis CI":
        return {CI_FILES[provider]: json.dumps({"script": list(commands)})}
    if provider == "Cirrus CI":
        return {CI_FILES[provider]: json.dumps({"task": {"container": {"image": "x"}, "script": list(commands)}})}
    return {CI_FILES[provider]: "".join(f"script: {command}\n" for command in commands)}


# A whole ecosystem that is not built in, from a plugin: detected by its build file and source suffix, judged
# by the practices it has rules for, and seen by --list.
ECOSYSTEM_PLUGIN = """
import re

from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns
from project_validator.facts.axes import versions_axis
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.tools import defined_by

CRYSTAL = Ecosystem(
    label="Crystal",
    languages=frozenset({"Crystal"}),
    build_systems=(BuildSystem(name="Shards", files=("shard.yml",), languages=frozenset({"Crystal"})),),
    source_suffixes={".cr": "Crystal"},
    toolchain=ToolchainPatterns(
        language="Crystal",
        versions=(re.compile(r"\\bcrystal:\\s*\\W?(\\d+\\.\\d+(?:\\.\\d+)?)"),),
        usage=re.compile(r"\\bcrystal\\s+spec\\b|\\bshards\\b"),
    ),
)
CRYSTAL_VERSIONS = versions_axis("Crystal version", "Crystal", frozenset({"Crystal"}))
CRYSTAL_FORMAT = format_tool(
    name="crystal tool format",
    languages=frozenset({"Crystal"}),
    can={Enforcement.CHECK: "crystal tool format --check", Enforcement.APPLY: "crystal tool format"},
    formats=flagged(("crystal", "tool", "format"), checks=("--check",)),
    style=defined_by(),
)
"""


CMAKE_PROJECT = "cmake_minimum_required(VERSION 3.21)\nproject(p LANGUAGES CXX)\n"


def in_cmake_project(
    test: unittest.TestCase, selected: Check, build: str, ci: Mapping[str, str] | None = None
) -> Result:
    """The result of `selected` in a CMake C++ project whose CMakeLists adds `build` to a bare `project()`."""
    return run_in_layout(test, "CMake C++", selected, {"CMakeLists.txt": CMAKE_PROJECT + build, **(ci or {})})


def in_meson_project(test: unittest.TestCase, selected: Check, build: str = "project('app', 'cpp')\n") -> Result:
    """The result of `selected` in a Meson C++ project with `build` as its meson.build."""
    return run_in_layout(test, "Meson C++", selected, {"meson.build": build})
