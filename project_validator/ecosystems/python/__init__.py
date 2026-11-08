"""Python: packaged with pyproject.toml or setup.py, judged by the interpreter versions CI runs."""

import re
import shlex
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from pathlib import PurePosixPath

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toml_members, toolchain_patterns
from project_validator.facts import Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.arguments import has_option, option_values, program, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Declared, Locked, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Launched, joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.licenses import declared_license_reader, toml_license
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, ini_settings, toml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Claim, Run, defined_by, either, starts, when
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.scanners import multi_language_scanners

PYTHON_ONLY = frozenset({"Python"})
PYTHON_PACKAGING = BuildSystem(
    name="Python packaging",
    files=("pyproject.toml", "setup.py"),
    languages=PYTHON_ONLY,
    members=toml_members("tool", "uv", "workspace"),
)


def _read_ruff(path: str, text: str) -> Iterator[Fact]:
    """ruff's settings: `[tool.ruff]` in pyproject.toml, or the whole of ruff.toml."""
    tables = ("tool", "ruff") if PurePosixPath(path).name == "pyproject.toml" else ()
    return toml_settings("ruff", path, text, *tables)


RUFF_SETTINGS = SettingsReader(name="ruff", files=("ruff.toml", ".ruff.toml", "pyproject.toml"), read=_read_ruff)
BLACK_SETTINGS = SettingsReader(
    name="black",
    files=("pyproject.toml",),
    read=lambda path, text: toml_settings("black", path, text, "tool", "black"),
)


RUFF_FORMAT = format_tool(
    name="ruff format",
    languages=PYTHON_ONLY,
    can={Enforcement.CHECK: "ruff format --check", Enforcement.APPLY: "ruff format"},
    # The ruff-format pre-commit hook applies it.
    formats=either(
        flagged(("ruff", "format"), checks=("--check", "--diff", "--exit-non-zero-on-format")),
        flagged(("ruff-format",), checks=()),
    ),
    style=defined_by(settings=("ruff",)),
    reads=("ruff",),
)
BLACK = format_tool(
    name="black",
    languages=PYTHON_ONLY,
    can={Enforcement.CHECK: "black --check", Enforcement.APPLY: "black"},
    formats=flagged(("black",), checks=("--check", "--diff")),
    style=defined_by(settings=("black",)),
    reads=("black",),
)
# The black action checks (`--check --diff`) unless its options say otherwise; ruff's action runs ruff's `args`.
BLACK_ACTION = Action(
    name="psf/black",
    runs=lambda inputs: (
        ("black", *shlex.split(inputs.get("options", "--check --diff")), *shlex.split(inputs.get("src", "."))),
    ),
)
RUFF_ACTION = Action(
    name="astral-sh/ruff-action", runs=lambda inputs: (("ruff", *shlex.split(inputs.get("args", "check"))),)
)


_TRUE = frozenset({"true", "1", "yes", "on"})
COVERAGE_FILES = (".coveragerc", "setup.cfg", "tox.ini", "pyproject.toml")


def _coverage_sections(path: str) -> Callable[[str], str | None]:
    """The INI sections coverage.py reads in `path`: `[run]` in its own file, `[coverage:run]` in any."""
    own = PurePosixPath(path).name not in ("setup.cfg", "tox.ini")

    def prefix(section: str) -> str | None:
        if section.startswith("coverage:"):
            return f"{section.removeprefix('coverage:')}."
        return f"{section}." if own else None

    return prefix


def _read_coverage_settings(path: str, text: str) -> Iterator[Fact]:
    if path.endswith(".toml"):
        return toml_settings("coverage.py", path, text, "tool", "coverage")
    return ini_settings("coverage.py", path, text, _coverage_sections(path))


def _named_rcfile(command: Command) -> list[str]:
    argv = resolved(command)
    if program(argv) not in ("coverage", "pytest", "py.test"):
        return []
    named = [*option_values(argv, "--rcfile", "--cov-config"), *filter(None, [command.env.get("COVERAGE_RCFILE")])]
    return [joined(command.directory, path) for path in named]


COVERAGE_PY_SETTINGS = SettingsReader(
    name="coverage.py", files=COVERAGE_FILES, read=_read_coverage_settings, named_by=_named_rcfile
)

# pytest reads its options from the first of these files with a pytest section.
_PYTEST_SECTIONS = {"pytest.ini": "pytest", "tox.ini": "pytest", "setup.cfg": "tool:pytest"}


def _read_pytest_settings(path: str, text: str) -> Iterator[Fact]:
    if path.endswith(".toml"):
        return toml_settings("pytest", path, text, "tool", "pytest", "ini_options")
    wanted = _PYTEST_SECTIONS[PurePosixPath(path).name]
    return ini_settings("pytest", path, text, lambda section: "" if section == wanted else None)


PYTEST_SETTINGS = SettingsReader(
    name="pytest", files=("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"), read=_read_pytest_settings
)


def _coverage_settings(command: Command, facts: Facts, named: str | None) -> Setting | None:
    """coverage.py's `run.branch` setting in the file it reads: the one it is given, else .coveragerc, else the first
    of setup.cfg, tox.ini and pyproject.toml with coverage settings."""
    candidates = [named] if named else [joined(command.directory, name) for name in COVERAGE_FILES]
    configuration = facts.configured("coverage.py", candidates)
    return facts.setting("coverage.py", "run.branch", paths=[configuration]) if configuration else None


def _branches(setting: Setting | None) -> bool:
    return setting is not None and (setting.value is True or str(setting.value).strip().lower() in _TRUE)


def _measured_lines_and(branch: bool, *read: Setting | None) -> Run:
    return measured(
        Granularity.LINE, Granularity.BRANCH if branch else None, read=[found for found in read if found is not None]
    )


def _coverage_py(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if not starts_with(argv, ("coverage", "run")):
        return None
    named = _named_rcfile(command)
    setting = _coverage_settings(command, facts, named[0] if named else None)
    return _measured_lines_and(has_option(argv, "--branch") or _branches(setting), setting)


def _pytest_cov(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if not starts_with(argv, ("pytest",), ("py.test",)):
        return None
    files = [joined(command.directory, name) for name in ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")]
    configuration = facts.configured("pytest", files)
    addopts = facts.setting("pytest", "addopts", paths=[configuration]) if configuration else None
    added = addopts.value if addopts is not None else ()
    words = (*argv, *(added if isinstance(added, tuple) else shlex.split(str(added))))
    if not has_option(words, "--cov"):
        return None
    named = [joined(command.directory, path) for path in option_values(tuple(words), "--cov-config")]
    setting = _coverage_settings(command, facts, named[0] if named else None)
    return _measured_lines_and(has_option(words, "--cov-branch") or _branches(setting), setting, addopts)


COVERAGE_PY = coverage_tool(
    name="coverage.py",
    languages=PYTHON_ONLY,
    can={Granularity.LINE: "coverage run", Granularity.BRANCH: "coverage run --branch"},
    measures=_coverage_py,
    reads=("coverage.py",),
)
PYTEST_COV = coverage_tool(
    name="pytest-cov",
    languages=PYTHON_ONLY,
    can={Granularity.LINE: "pytest --cov", Granularity.BRANCH: "pytest --cov --cov-branch"},
    measures=_pytest_cov,
    reads=("pytest", "coverage.py"),
)

_PYTHON = re.compile(r"python(?:\d+(?:\.\d+)?)?|pypy\d*|py")
# Interpreter options that take a value (`-W error`).
_INTERPRETER_VALUES = frozenset({"-W", "-X", "--check-hash-based-pycs"})


def _python_module(command: Command, _: Context) -> list[Expansion] | None:
    """`python -m module`: the module runs as its command does (`python -m pytest` as `pytest`)."""
    argv = resolved(command)
    if not _PYTHON.fullmatch(program(argv)):
        return None
    words = iter(argv[1:])
    for word in words:
        if word == "-m" or (word.startswith("-m") and len(word) > 2):
            module = word[2:] or next(words, "")
            return [Launched(argv=(module, *words))] if module else []
        if word in _INTERPRETER_VALUES:
            next(words, None)
        elif not word.startswith("-") or word in ("-", "-c"):
            return None
    return None


PYTHON_MODULES = CommandExpander(name="python -m", expand=_python_module)
# coverage.py's options that take a value, before the module or script it runs.
_COVERAGE_RUN_VALUES = frozenset(
    {"--rcfile", "--source", "--include", "--omit", "--context", "--data-file", "--concurrency"}
)


def _coverage_run(command: Command, _: Context) -> list[Expansion] | None:
    """`coverage run -m module`: coverage.py runs the module as `python -m` does (`coverage run -m pytest`)."""
    argv = resolved(command)
    if argv[:2] != ("coverage", "run"):
        return None
    words = iter(argv[2:])
    for word in words:
        if word == "-m":
            module = next(words, "")
            return [Launched(argv=(module, *words))] if module else []
        if word in _COVERAGE_RUN_VALUES:
            next(words, None)
        elif not word.startswith("-"):
            return None
    return None


COVERAGE_RUN = CommandExpander(name="coverage run -m", expand=_coverage_run)
# The runners that run a command in the project's environment.
PYTHON_RUNNERS = launcher(
    "Python environment runners",
    (("uv", "run"), ("uvx",), ("poetry", "run"), ("pipenv", "run"), ("pdm", "run"), ("hatch", "run"), ("pipx", "run")),
    with_values=frozenset(
        {
            "--with",
            "--python",
            "-p",
            "--group",
            "--only-group",
            "--no-group",
            "--extra",
            "--package",
            "--directory",
            "--project",
            "--env-file",
            "--from",
            "--spec",
            "--index",
        }
    ),
)


PYTHON_TEST_FILES = TestFiles(
    name="test_*.py or *_test.py files",
    languages=PYTHON_ONLY,
    path=re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$"),
)
_PYTHON_TESTS = tests_of(PYTHON_TEST_FILES.name)


def _runs_tests(*programs: str, heuristic: bool = False) -> Claim:
    return lambda command, _facts: tested(heuristic=heuristic) if program(resolved(command)) in programs else None


PYTEST = test_runner(
    name="pytest", languages=PYTHON_ONLY, how="pytest", runs=_runs_tests("pytest", "py.test"), tests=_PYTHON_TESTS
)
# `python -m unittest` runs as `unittest` (see PYTHON_MODULES).
UNITTEST = test_runner(
    name="unittest", languages=PYTHON_ONLY, how="unittest", runs=_runs_tests("unittest"), tests=_PYTHON_TESTS
)
# nox's sessions are Python code, which is not read: a nox run is taken to run the tests.
NOX = test_runner(
    name="nox", languages=PYTHON_ONLY, how="nox", runs=_runs_tests("nox", heuristic=True), tests=_PYTHON_TESTS
)


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


WARNING_SETTINGS_FILES = ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini")

# Python reports problems such as deprecations as warnings; the strict setting turns every one into an error.
PYTHON_WARNINGS = (
    _setting(
        "-W error",
        r"\bpython[\d.]*\s+(?:-\w+(?:\s+[^-\s]\S*)?\s+)*-W\s*error\b|\bpytest\b[^\n]*\s-W\s*error\b"
        r"|\bPYTHONWARNINGS\W+error\b|\bfilterwarnings\s*=\s*\[?\s*[\"']?error\b",
    ),
)


_PYTHON_WARNINGS = tuple(
    replace(required(warning), hints=("-W", "PYTHONWARNINGS", "filterwarnings")) for warning in PYTHON_WARNINGS
)
PYTHON_WARNING_SETTINGS = requirement_reader("Python warning settings", WARNING_SETTINGS_FILES, _PYTHON_WARNINGS)
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=PYTHON_ONLY,
    requirements=always(*_PYTHON_WARNINGS),
    reads=(PYTHON_WARNING_SETTINGS.name,),
    words=Wording(
        kind="Python warning settings",
        separator=" ",
        hint='run the tests with -W error (or filterwarnings = ["error"] in the pytest settings)',
    ),
)

# Python builds no binary, so it has no hardening rule: its interpreter is hardened by whoever builds it.
_BANDIT_RULES = re.compile(r"S\d*|ALL")
_RULE_SELECTIONS = ("lint.select", "lint.extend-select", "select", "extend-select")


def _selects_bandit(values: Iterable[object]) -> bool:
    return any(_BANDIT_RULES.fullmatch(str(value).strip()) for value in values)


def _ruff_security(command: Command, facts: Facts) -> Run | None:
    """`ruff check` with flake8-bandit's rules (`S`) selected, on its command line or in its settings."""
    argv = resolved(command)
    if not starts_with(argv, ("ruff", "check")):
        return None
    if _selects_bandit(
        rule for value in option_values(argv, "--select", "--extend-select") for rule in value.split(",")
    ):
        return scanned()
    read = [
        setting
        for setting in facts.settings("ruff")
        if setting.key in _RULE_SELECTIONS and isinstance(setting.value, tuple) and _selects_bandit(setting.value)
    ]
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(name="bandit", languages=PYTHON_ONLY, how="bandit -r .", scans=when(starts(("bandit",)), scanned)),
    scanner(
        name="ruff's bandit rules",
        languages=PYTHON_ONLY,
        how="ruff check with S selected",
        scans=_ruff_security,
        reads=("ruff",),
    ),
    *multi_language_scanners(PYTHON_ONLY),
)
BANDIT_ACTION = Action(name="PyCQA/bandit-action", runs=lambda _inputs: (("bandit", "-r", "."),))

AUDITORS = (
    auditor(name="pip-audit", languages=PYTHON_ONLY, how="pip-audit", audits=when(starts(("pip-audit",)), audited)),
    auditor(
        name="safety",
        languages=PYTHON_ONLY,
        how="safety scan",
        audits=when(starts(("safety", "scan"), ("safety", "check")), audited),
    ),
    *multi_ecosystem_audits(PYTHON_ONLY),
)
PIP_AUDIT_ACTION = Action(name="pypa/gh-action-pip-audit", runs=lambda _inputs: (("pip-audit",),))

BYTECODE = BuildOutput(
    languages=PYTHON_ONLY,
    name="Python bytecode",
    globs=ignored_at_top_level(r"__pycache__|\*\.py(?:c|\[[cod]+\])"),
    paths=(*directories("__pycache__"), "module.pyc"),
    hint="consider ignoring __pycache__/ and *.py[cod]",
    artifacts=("__pycache__/", "*.pyc", "*.pyo", "*.egg-info/", "/dist/", "/build/"),
)

PYPROJECT_LICENSE = declared_license_reader(
    name="pyproject.toml license", files=("pyproject.toml",), languages=PYTHON_ONLY, declared=toml_license("project")
)


LOCKFILES = ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock", "pylock.toml", "pylock.*.toml")
HASH = re.compile(r"--hash[=\s]+\w+:")
SETUP_REQUIRES = re.compile(r"\binstall_requires\s*=")
PYTHON_PACKAGES = "Python packages"


def _pyproject_declares(_path: str, text: str) -> bool:
    """A pyproject.toml declares dependencies in `[project]`, or Poetry's, beyond Python itself."""
    manifest = tomllib.loads(text)
    project = manifest.get("project")
    tool = manifest.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    poetry_dependencies = poetry.get("dependencies") if isinstance(poetry, dict) else None
    declared = isinstance(project, dict) and bool(project.get("dependencies"))
    return declared or (isinstance(poetry_dependencies, dict) and bool(set(poetry_dependencies) - {"python"}))


PYPROJECT_DEPENDENCIES = manifest_reader(
    name="Python dependencies",
    manager=PYTHON_PACKAGES,
    files=("pyproject.toml",),
    declares=_pyproject_declares,
)
SETUP_PY_DEPENDENCIES = manifest_reader(
    name="setup.py dependencies",
    manager=PYTHON_PACKAGES,
    files=("setup.py",),
    declares=lambda _path, text: bool(SETUP_REQUIRES.search(text)),
)


def _read_requirements(path: str, text: str) -> Iterator[Fact]:
    """A requirements file declares dependencies, but CI's own (in `.github`, which pin the tools it installs); one
    that pins them by hash locks them."""
    origin = Origin(path=path)
    if not path.startswith("."):
        yield Declared(origin=origin, manager=PYTHON_PACKAGES)
    if HASH.search(text):
        yield Locked(origin=origin, manager=PYTHON_PACKAGES)


REQUIREMENTS = SettingsReader(
    name="requirements files",
    files=("*requirements*.txt", "requirements/*.txt", ".github/*requirements*.txt"),
    read=_read_requirements,
)
PYTHON_LOCKFILES = lockfile_reader(manager=PYTHON_PACKAGES, files=LOCKFILES)
PYTHON_PACKAGE_MANAGER = PackageManager(
    name=PYTHON_PACKAGES,
    languages=PYTHON_ONLY,
    lock_hint="lock them: commit uv.lock (uv lock), poetry.lock, pdm.lock or pylock.toml, or pin requirements "
    "with hashes (pip-compile --generate-hashes) and install them with --require-hashes",
)


PYTHON = Ecosystem(
    label="Python",
    languages=PYTHON_ONLY,
    build_systems=(PYTHON_PACKAGING,),
    source_suffixes={".py": "Python", ".pyi": "Python"},
    toolchain=toolchain_patterns(
        "Python",
        version=r"(\d+(?:\.(?:\d+|x))*|pypy[\d.]*)",
        inputs=("python-version",),
        images=("python",),
        image_version=r"(\d+(?:\.\d+)*)",
        more=(r"\bpython(\d\.\d+)\b",),
        commands=r"\bpython[\d.]*\s+(?:-|\S+\.py\b)|\bpip\d*\s+install\b|\bpytest\b|\btox\b|\bnox\b",
        setup=("python",),
    ),
)

PYTHON_VERSIONS = versions_axis("Python version", "Python", PYTHON_ONLY)
