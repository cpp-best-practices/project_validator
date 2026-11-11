"""Python's static analyzers (ruff check, pylint, flake8) and type checkers (mypy, pyright, pyrefly, ty), with the
settings that configure them: a dedicated file, a `[tool.<name>]` table of pyproject.toml, or an INI section."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from project_validator.facts import Command, Fact, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import has_option, program
from project_validator.facts.expansion import Action, from_hook
from project_validator.facts.settings import Read, SettingsReader, ini_settings, json_settings, toml_settings
from project_validator.facts.tools import Run, defined_by, starts
from project_validator.tools.limits import function_length_limiters

PYTHON = frozenset({"Python"})
_TRUE = frozenset({"true", "1", "yes", "on"})


def _reads(tool: str, *, tables: tuple[str, ...] = (), section: str | None = None) -> Read:
    """`tool`'s settings: its `[tool.<table>]` tables in pyproject.toml, its INI `section` (every section when None)
    of an INI file, or the whole of its own TOML or JSON file."""

    def read(path: str, text: str) -> Iterable[Fact]:
        name = PurePosixPath(path).name
        if name == "pyproject.toml":
            return (fact for table in tables for fact in toml_settings(tool, path, text, "tool", table))
        if name.endswith(".toml"):
            return toml_settings(tool, path, text)
        if name.endswith(".json"):
            return json_settings(tool, path, text, comments=True)
        sections: Callable[[str], str | None] = (
            (lambda found: f"{found}.") if section is None else (lambda found: "" if found == section else None)
        )
        return ini_settings(tool, path, text, sections)

    return read


PYLINT_SETTINGS = SettingsReader(
    name="pylint", files=(".pylintrc", "pylintrc", "pyproject.toml"), read=_reads("pylint", tables=("pylint",))
)
FLAKE8_SETTINGS = SettingsReader(
    name="flake8", files=(".flake8", "setup.cfg", "tox.ini"), read=_reads("flake8", section="flake8")
)
MYPY_SETTINGS = SettingsReader(
    name="mypy",
    files=("mypy.ini", ".mypy.ini", "setup.cfg", "pyproject.toml"),
    read=_reads("mypy", tables=("mypy",), section="mypy"),
)
PYRIGHT_SETTINGS = SettingsReader(
    name="pyright",
    files=("pyrightconfig.json", "pyproject.toml"),
    read=_reads("pyright", tables=("pyright", "basedpyright")),
)
PYREFLY_SETTINGS = SettingsReader(
    name="pyrefly", files=("pyrefly.toml", "pyproject.toml"), read=_reads("pyrefly", tables=("pyrefly",))
)
TY_SETTINGS = SettingsReader(name="ty", files=("ty.toml", "pyproject.toml"), read=_reads("ty", tables=("ty",)))


def _programs(*names: str, subcommand: str | None = None) -> Callable[[Command], bool]:
    """Whether a command runs one of the programs `names` (with `subcommand`, when given)."""
    return starts(*((name,) if subcommand is None else (name, subcommand) for name in names))


def _analyses(runs: Callable[[Command], bool]) -> Callable[[Command, Facts], Run | None]:
    return lambda command, _facts: analysed() if runs(command) else None


def _ruff_check(command: Command) -> bool:
    """`ruff check`, and ruff's lint hooks (`ruff`, `ruff-check`); `ruff-format` only formats."""
    argv = resolved(command)
    if program(argv) == "ruff-check":
        return True
    return program(argv) == "ruff" and (argv[1:2] == ("check",) or (from_hook(command) and argv[1:2] != ("format",)))


RUFF_CHECK = analyzer(
    name="ruff check",
    languages=PYTHON,
    how="ruff check",
    analyses=_analyses(_ruff_check),
    rules=defined_by(named=("ruff.toml", ".ruff.toml"), settings=("ruff",)),
    reads=("ruff",),
)
PYLINT = analyzer(
    name="pylint",
    languages=PYTHON,
    how="pylint",
    analyses=_analyses(_programs("pylint")),
    rules=defined_by(named=(".pylintrc", "pylintrc"), settings=("pylint",)),
    reads=("pylint",),
)
FLAKE8 = analyzer(
    name="flake8",
    languages=PYTHON,
    how="flake8",
    analyses=_analyses(_programs("flake8", "pflake8", "flake8p")),
    rules=defined_by(named=(".flake8",), settings=("flake8",)),
    reads=("flake8",),
)


def _enabled(setting: Setting | None, *values: str) -> bool:
    if setting is None:
        return False
    if isinstance(setting.value, bool):
        return setting.value
    return str(setting.value).strip().lower() in (values or _TRUE)


def _mypy(command: Command, facts: Facts) -> Run | None:
    """mypy (or dmypy, or its pre-commit hook), strict with `--strict` or `strict = true` in its configuration."""
    if not _programs("mypy", "dmypy")(command):
        return None
    setting = facts.setting("mypy", "strict")
    strict = has_option(resolved(command), "--strict") or _enabled(setting)
    return type_checked(strict=strict, read=[setting] if setting else ())


def _pyright(command: Command, facts: Facts) -> Run | None:
    """pyright or basedpyright, strict when its `typeCheckingMode` is strict (or basedpyright's all)."""
    if not _programs("pyright", "basedpyright")(command):
        return None
    setting = facts.setting("pyright", "typeCheckingMode")
    return type_checked(strict=_enabled(setting, "strict", "all"), read=[setting] if setting else ())


def _checks(runs: Callable[[Command], bool]) -> Callable[[Command, Facts], Run | None]:
    return lambda command, _facts: type_checked(strict=False) if runs(command) else None


MYPY = type_checker(
    name="mypy",
    languages=PYTHON,
    can={Strictness.CHECKS: "mypy", Strictness.STRICT: "strict = true in [tool.mypy] (or mypy --strict)"},
    checks=_mypy,
    configuration=defined_by(named=("mypy.ini", ".mypy.ini"), settings=("mypy",)),
    reads=("mypy",),
)
PYRIGHT = type_checker(
    name="pyright",
    languages=PYTHON,
    can={Strictness.CHECKS: "pyright (or basedpyright)", Strictness.STRICT: "pyright's typeCheckingMode = strict"},
    checks=_pyright,
    configuration=defined_by(named=("pyrightconfig.json",), settings=("pyright",)),
    reads=("pyright",),
)
PYREFLY = type_checker(
    name="pyrefly",
    languages=PYTHON,
    can={Strictness.CHECKS: "pyrefly check"},
    checks=_checks(_programs("pyrefly")),
    configuration=defined_by(named=("pyrefly.toml",), settings=("pyrefly",)),
    reads=("pyrefly",),
)
TY = type_checker(
    name="ty",
    languages=PYTHON,
    can={Strictness.CHECKS: "ty check"},
    checks=_checks(_programs("ty", subcommand="check")),
    configuration=defined_by(named=("ty.toml",), settings=("ty",)),
    reads=("ty",),
)
PYRIGHT_ACTION = Action(name="jakebailey/pyright-action", runs=lambda _inputs: (("pyright",),))

# Python has no function length limit of its own here; lizard measures it.
FUNCTION_LENGTH_LIMITERS = function_length_limiters(PYTHON)
