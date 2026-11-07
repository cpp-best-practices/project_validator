"""Python: packaged with pyproject.toml or setup.py, judged by the interpreter versions CI runs."""

import re
import shlex
from collections.abc import Callable, Iterator
from fnmatch import fnmatch
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, toml_members, versions_axis
from project_validator.evidence import (
    ci_and_hook_texts,
    configuration,
    existing_texts,
    toml_value,
)
from project_validator.facts import Command, Fact, Facts, Setting, resolved
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Launched, joined, launcher
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.settings import SettingsReader, ini_settings, toml_settings
from project_validator.facts.tools import Run, defined_by, either
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    Analyzer,
    BuildOutputs,
    DependencyAudit,
    DependencyManagement,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    TypeChecking,
    WarningPolicy,
    directories,
    ignored_at_top_level,
    toml_license,
)
from project_validator.text import Pattern, pattern

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
    formats=either(flagged(("ruff", "format"), checks=("--check", "--diff")), flagged(("ruff-format",), checks=())),
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
    if program(argv) != "coverage" or argv[1:2] != ("run",):
        return None
    named = _named_rcfile(command)
    setting = _coverage_settings(command, facts, named[0] if named else None)
    return _measured_lines_and(has_option(argv, "--branch") or _branches(setting), setting)


def _pytest_cov(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) not in ("pytest", "py.test"):
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


PYTHON_TEST_FILES = ("test_*.py", "*_test.py")
RUNS_PYTHON_TESTS = (pattern("Python tests", r"\bpytest\b|\bunittest\b|\btox\b|\bnox\b"),)


def _python_tests_result(context: Context) -> Result:
    names = (PurePosixPath(path).name for path in context.project.files() if path.endswith(".py"))
    count = sum(1 for name in names if any(fnmatch(name, test_file) for test_file in PYTHON_TEST_FILES))
    if count == 0:
        return Result.failed(f"no Python tests found ({' or '.join(PYTHON_TEST_FILES)} files)")
    return Result.passed(f"Python tests found in {count} file(s)")


TESTS = TestSuite(found=_python_tests_result, runs=RUNS_PYTHON_TESTS, runner="pytest, unittest, tox or nox")


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


def _required_warnings(_: Context) -> tuple[Pattern, ...]:
    return PYTHON_WARNINGS


def _warning_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *existing_texts(context, WARNING_SETTINGS_FILES))


WARNINGS = WarningPolicy(
    kind="Python warning settings", recognised=PYTHON_WARNINGS, required=_required_warnings, texts=_warning_texts
)

SECURITY_SETTINGS_FILES = (
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "ruff.toml",
    ".ruff.toml",
    ".pre-commit-config.yaml",
)


def _security_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *existing_texts(context, SECURITY_SETTINGS_FILES))


# Python builds no binary, so it has no hardening rule: its interpreter is hardened by whoever builds it.
SECURITY_LINTS = SecurityLints(
    texts=_security_texts,
    lints=(
        _setting(
            "bandit security lints",
            r"\bbandit\s+-|\bid:\s*bandit\b|\bPyCQA/bandit-action\b"
            r"""|\bruff\b[^\n]*--(?:extend-)?select[=\s]+(?:\S*,)?(?:S\d*|ALL)(?![\w-])"""
            r"""|\b(?:extend-)?select\s*=\s*\[[^\]]*["'](?:S\d*|ALL)["']""",
        ),
    ),
)

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        pattern("pip-audit", r"\bpip-audit\b|\bpypa/gh-action-pip-audit\b"),
        pattern("safety", r"\bsafety\s+(?:check|scan)\b"),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="consider running pip-audit in CI (pypa/gh-action-pip-audit, or pip-audit -r requirements.txt)",
)

BYTECODE = BuildOutputs(
    name="Python bytecode",
    globs=ignored_at_top_level(r"__pycache__|\*\.py(?:c|\[[cod]+\])"),
    paths=(*directories("__pycache__"), "module.pyc"),
    hint="consider ignoring __pycache__/ and *.py[cod]",
    artifacts=("__pycache__/", "*.pyc", "*.pyo", "*.egg-info/", "/dist/", "/build/"),
)

LICENSE = toml_license("pyproject.toml", "project")


def _section(name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*\[{re.escape(name)}\b", re.MULTILINE)


STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(
            name="ruff check",
            # ruff's pre-commit hook is `ruff` (or `ruff-check`); `ruff-format` only formats.
            runs=re.compile(r"\bruff\s+check\b|\bastral-sh/ruff-action\b|\bid:\s*ruff(?:-check)?\s*$", re.MULTILINE),
            configured=configuration(("ruff.toml", ".ruff.toml"), {"pyproject.toml": _section("tool.ruff")}),
        ),
        Analyzer(
            name="pylint",
            runs=re.compile(r"\bpylint\b"),
            configured=configuration((".pylintrc", "pylintrc"), {"pyproject.toml": _section("tool.pylint")}),
        ),
        Analyzer(
            name="flake8",
            runs=re.compile(r"\bflake8\b"),
            configured=configuration((".flake8",), {"setup.cfg": _section("flake8"), "tox.ini": _section("flake8")}),
        ),
    ),
    texts=ci_and_hook_texts,
    hint="consider running ruff check (or pylint or flake8) in CI",
)

# mypy reads its [mypy] section from these files, and [tool.mypy] from pyproject.toml.
MYPY_INI_FILES = ("mypy.ini", ".mypy.ini", "setup.cfg")
MYPY_STRICT_SETTING = re.compile(r"^\[mypy\][^\[]*^\s*strict\s*=\s*(?:true|1|yes|on)\b", re.MULTILINE | re.IGNORECASE)
MYPY_STRICT_FLAG = re.compile(r"\bmypy\b[^\n]*\s--strict\b")
PYRIGHT_STRICT_MODE = re.compile(r"""\btypeCheckingMode["']?\s*[:=]\s*["'](?:strict|all)["']""")


def _strict_type_checking(context: Context) -> str | None:
    """Where strict type checking is enabled: mypy's strict setting or flag, or pyright's strict mode."""
    if toml_value(context, "pyproject.toml", "tool", "mypy", "strict") is True:
        return "mypy strict = true in pyproject.toml"
    strict_files = (
        *((path, MYPY_STRICT_SETTING, "mypy strict = true") for path in MYPY_INI_FILES),
        *((path, PYRIGHT_STRICT_MODE, "pyright typeCheckingMode") for path in ("pyrightconfig.json", "pyproject.toml")),
    )
    for path, setting, name in strict_files:
        if context.project.exists(path) and setting.search(context.project.read_text(path)):
            return f"{name} in {path}"
    return "mypy --strict" if any(map(MYPY_STRICT_FLAG.search, ci_and_hook_texts(context))) else None


def _tool_configuration(name: str, *files: str) -> Callable[[Context], str | None]:
    return configuration(files, {"pyproject.toml": _section(f"tool.{name}")})


TYPE_CHECKING = TypeChecking(
    checkers=(
        Analyzer(
            name="mypy",
            runs=re.compile(r"\b(?:d?mypy|mirrors-mypy)\b"),
            configured=configuration(
                ("mypy.ini", ".mypy.ini"), {"pyproject.toml": _section("tool.mypy"), "setup.cfg": _section("mypy")}
            ),
        ),
        Analyzer(
            name="pyright",
            runs=re.compile(r"\b(?:based)?pyright\b"),
            configured=configuration(
                ("pyrightconfig.json",),
                {"pyproject.toml": re.compile(r"^\s*\[tool\.(?:based)?pyright\b", re.MULTILINE)},
            ),
        ),
        Analyzer(
            name="pyrefly", runs=re.compile(r"\bpyrefly\b"), configured=_tool_configuration("pyrefly", "pyrefly.toml")
        ),
        Analyzer(name="ty", runs=re.compile(r"\bty\s+check\b"), configured=_tool_configuration("ty", "ty.toml")),
    ),
    texts=ci_and_hook_texts,
    strict=_strict_type_checking,
    hint="consider running a type checker in CI: mypy, pyright (or basedpyright), pyrefly or ty",
    strict_hint="consider enabling strict mode: strict = true in [tool.mypy], or pyright's typeCheckingMode = strict",
)

LOCKFILES = ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock", "pylock.toml")
NAMED_LOCKFILE = re.compile(r"pylock\.[^/]+\.toml")
REQUIREMENTS_FILE = re.compile(r"(?:^|/)(?:[^/]*requirements[^/]*\.txt|requirements/[^/]+\.txt)$")
HASH = re.compile(r"--hash[=\s]+\w+:")
SETUP_REQUIRES = re.compile(r"\binstall_requires\s*=")


def _declared_dependencies(context: Context) -> str | None:
    """Where the project declares the dependencies it needs: its manifest, or requirements files."""
    poetry = toml_value(context, "pyproject.toml", "tool", "poetry", "dependencies")
    if toml_value(context, "pyproject.toml", "project", "dependencies") or (
        isinstance(poetry, dict) and set(poetry) - {"python"}
    ):
        return "declared in pyproject.toml"
    if context.project.exists("setup.py") and SETUP_REQUIRES.search(context.project.read_text("setup.py")):
        return "declared in setup.py"
    requirements = next((path for path in context.tracked_files if REQUIREMENTS_FILE.search(path)), None)
    return f"declared in {requirements}" if requirements else None


def _locked_dependencies(context: Context) -> str | None:
    """A committed lockfile, or requirements files that pin every package by hash."""
    lockfiles = [*LOCKFILES, *(path for path in context.tracked_files if NAMED_LOCKFILE.fullmatch(path))]
    if lockfile := next((path for path in lockfiles if context.committed(path)), None):
        return lockfile
    requirements = [path for path in context.tracked_files if REQUIREMENTS_FILE.search(path)]
    hashed = [path for path in requirements if HASH.search(context.project.read_text(path))]
    if not hashed:
        return None
    return hashed[0] if len(hashed) == 1 else f"{len(hashed)} hash-pinned requirements files"


DEPENDENCIES = DependencyManagement(
    managed=_declared_dependencies,
    locked=_locked_dependencies,
    lock_hint="lock them: commit uv.lock (uv lock), poetry.lock, pdm.lock or pylock.toml, or pin requirements "
    "with hashes (pip-compile --generate-hashes) and install them with --require-hashes",
)


PYTHON = Ecosystem(
    label="Python",
    languages=PYTHON_ONLY,
    build_systems=(PYTHON_PACKAGING,),
    source_suffixes={".py": "Python", ".pyi": "Python"},
    toolchain=ToolchainPatterns(
        language="Python",
        versions=(
            re.compile(r"\bpython-version\W+(\d+(?:\.(?:\d+|x))*|pypy[\d.]*)"),
            re.compile(r"\bpython:(\d+(?:\.\d+)*)"),
            re.compile(r"\bpython(\d\.\d+)\b"),
        ),
        usage=re.compile(
            r"\bpython[\d.]*\s+(?:-|\S+\.py\b)|\bpip\d*\s+install\b|\bpytest\b|\btox\b|\bnox\b|\bsetup-python\b"
        ),
    ),
    rules=(
        versions_axis("Python version", "Python"),
        TESTS,
        WARNINGS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(),
        STATIC_ANALYSIS,
        TYPE_CHECKING,
        DEPENDENCIES,
        BYTECODE,
        LICENSE,
    ),
)
