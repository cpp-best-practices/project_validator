"""clang-tidy's settings (a `.clang-tidy`: the checks it enables and their options), and its readability-function-size
check, which limits C/C++ function length when clang-tidy runs with a line or statement threshold."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from fnmatch import fnmatchcase

from project_validator.ecosystems.c_cpp.analysis import CLANG_TIDY
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Fact, Facts, Setting
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.settings import SettingsReader, yaml_settings
from project_validator.tools.limits import function_length_limiters

CLANG_TIDY_CHECK = "readability-function-size"
LENGTH_THRESHOLDS = ("LineThreshold", "StatementThreshold")


def _read_clang_tidy(path: str, text: str) -> Iterator[Fact]:
    return yaml_settings("clang-tidy", path, text)


CLANG_TIDY_SETTINGS = SettingsReader(name="clang-tidy", files=(".clang-tidy",), read=_read_clang_tidy)


def check_globs(checks: object) -> tuple[str, ...]:
    joined = ",".join(map(str, checks)) if isinstance(checks, tuple) else str(checks or "")
    return tuple(glob for glob in (part.strip() for part in joined.split(",")) if glob)


def is_enabled(name: str, globs: tuple[str, ...]) -> bool:
    """clang-tidy lets the last glob matching a check decide whether it is enabled."""
    decisions = (not glob.startswith("-") for glob in reversed(globs) if fnmatchcase(name, glob.removeprefix("-")))
    return next(decisions, False)


def _is_positive(value: object) -> bool:
    text = str(value).strip()
    return text.isdigit() and int(text) > 0


def _options(settings: Sequence[Setting]) -> Iterator[tuple[Setting, object, object]]:
    """(setting, key, value) for each check option: `CheckOptions` is a mapping, or a list of `key`/`value` pairs."""
    for setting in settings:
        if setting.key.startswith("CheckOptions."):
            yield setting, setting.key.removeprefix("CheckOptions."), setting.value
        elif setting.key == "CheckOptions" and isinstance(setting.value, tuple):
            pairs = (option for option in setting.value if isinstance(option, Mapping))
            yield from ((setting, option.get("key"), option.get("value")) for option in pairs)


def _thresholds(settings: Sequence[Setting]) -> list[Setting]:
    wanted = {f"{CLANG_TIDY_CHECK}.{name}" for name in LENGTH_THRESHOLDS}
    return [setting for setting, key, value in _options(settings) if key in wanted and _is_positive(value)]


def _function_size(facts: Facts) -> list[Setting]:
    """The settings of each `.clang-tidy` that enables readability-function-size with a positive threshold."""
    found: list[Setting] = []
    for path in dict.fromkeys(setting.path for setting in facts.settings("clang-tidy")):
        settings = facts.settings("clang-tidy", paths=(path,))
        checks = next((setting for setting in settings if setting.key == "Checks"), None)
        thresholds = _thresholds(settings)
        if checks is not None and is_enabled(CLANG_TIDY_CHECK, check_globs(checks.value)) and thresholds:
            found += [checks, *thresholds]
    return found


FUNCTION_SIZE = limiter(
    name="clang-tidy's readability-function-size",
    languages=C_FAMILY,
    how="clang-tidy with readability-function-size and a LineThreshold in .clang-tidy",
    runs=CLANG_TIDY.claims,
    rule=Rule(
        describe=f"{CLANG_TIDY_CHECK} with a LineThreshold or StatementThreshold in .clang-tidy",
        enabled=_function_size,
    ),
    reads=("CMake", "clang-tidy"),
)
FUNCTION_LENGTH_LIMITERS = (FUNCTION_SIZE, *function_length_limiters(C_FAMILY))
