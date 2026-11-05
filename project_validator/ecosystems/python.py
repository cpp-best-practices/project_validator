"""Python: packaged with pyproject.toml or setup.py, judged by the interpreter versions CI runs."""

import re
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, configuration, existing_texts, first_existing, toml_value
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    Analyzer,
    BuildOutputs,
    CoverageTools,
    DependencyAudit,
    Formatter,
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

PYTHON_PACKAGING = BuildSystem(
    name="Python packaging", files=("pyproject.toml", "setup.py"), languages=frozenset({"Python"})
)

PYTHON_FORMATTER_SECTIONS = re.compile(r"^\s*\[tool\.(?:ruff|black)\b", re.MULTILINE)


def _python_formatter_file(context: Context) -> str | None:
    project = context.project
    if project.exists("pyproject.toml") and PYTHON_FORMATTER_SECTIONS.search(project.read_text("pyproject.toml")):
        return "pyproject.toml"
    return first_existing(context, ("ruff.toml", ".ruff.toml"))


RUFF_OR_BLACK = Formatter(
    name="ruff format or black",
    config_file=_python_formatter_file,
    runs=(
        pattern("ruff format", r"\bruff\s+format\b"),
        pattern("black", r"(?<![\w.-])black\b[^\n]*\s--(?:check|diff)\b|\bpsf/black@"),
    ),
    hint="consider a CI job that runs ruff format --check (or black --check)",
    default_style=True,
)

COVERAGE_SETTINGS_FILES = ("pyproject.toml", "setup.cfg", "tox.ini", ".coveragerc")


def _ci_and_coverage_settings_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *existing_texts(context, COVERAGE_SETTINGS_FILES))


COVERAGE = CoverageTools(
    searched="CI configuration or coverage.py settings",
    texts=_ci_and_coverage_settings_texts,
    branch=(
        pattern("coverage.py", r"\bcoverage\s+run\b[^\n]*--branch\b"),
        pattern("pytest-cov", r"--cov-branch\b"),
        Pattern(
            "coverage.py branch = true",
            re.compile(r"^\s*branch\s*=\s*(true|1|yes|on)\b", re.IGNORECASE | re.MULTILINE),
        ),
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

PYTHON = Ecosystem(
    label="Python",
    languages=frozenset({"Python"}),
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
        RUFF_OR_BLACK,
        COVERAGE,
        TESTS,
        WARNINGS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(),
        STATIC_ANALYSIS,
        TYPE_CHECKING,
        BYTECODE,
        LICENSE,
    ),
)
