"""JavaScript and TypeScript's static analyzers (eslint, biome, oxlint, deno lint) and type checkers (tsc, deno
check), with the configuration that defines their rules and strictness."""

import re
from collections.abc import Callable
from pathlib import PurePosixPath

from project_validator.ecosystems.javascript import DENO_CONFIG_FILES, ESLINT_CONFIG_FILES, JS_LANGUAGES, PACKAGE_JSON
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import option_values, program
from project_validator.facts.expansion import joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, json_settings, matched_settings
from project_validator.facts.tools import Run, combined, defined_by
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

ESLINT_FILES = file_reader("eslint", ESLINT_CONFIG_FILES)
OXLINT_FILES = file_reader("oxlint", (".oxlintrc.json",))
TSCONFIG_FILES = ("tsconfig.json", "jsconfig.json")
TYPESCRIPT_SETTINGS = SettingsReader(
    name="TypeScript",
    files=(*TSCONFIG_FILES, "tsconfig.*.json"),
    read=lambda path, text: json_settings("TypeScript", path, text, comments=True),
)
DENO_SETTINGS = SettingsReader(
    name="Deno", files=DENO_CONFIG_FILES, read=lambda path, text: json_settings("Deno", path, text, comments=True)
)
# @tsconfig/strictest turns on strict, and more.
_STRICTEST = re.compile(r"@tsconfig/strictest\b")


def _programs(*prefixes: tuple[str, ...]) -> Callable[[Command], bool]:
    def runs(command: Command) -> bool:
        argv = resolved(command)
        return any(program(argv) == prefix[0] and argv[1 : len(prefix)] == prefix[1:] for prefix in prefixes)

    return runs


def _analyses(runs: Callable[[Command], bool]) -> Callable[[Command, Facts], Run | None]:
    return lambda command, _facts: analysed() if runs(command) else None


ESLINT = analyzer(
    name="eslint",
    languages=JS_LANGUAGES,
    how="eslint",
    analyses=_analyses(_programs(("eslint",), ("next", "lint"))),
    rules=defined_by(files=("eslint",)),
)
OXLINT = analyzer(
    name="oxlint",
    languages=JS_LANGUAGES,
    how="oxlint",
    analyses=_analyses(_programs(("oxlint",))),
    rules=defined_by(files=("oxlint",)),
)
DENO_LINT = analyzer(
    name="deno lint",
    languages=JS_LANGUAGES,
    how="deno lint",
    analyses=_analyses(_programs(("deno", "lint"))),
    rules=defined_by(settings=("Deno",)),
    reads=("Deno",),
)
# biome formats and lints: `biome lint` lints, `biome check` and `biome ci` do both.
BIOME = combined(
    format_tool(
        name="biome",
        languages=JS_LANGUAGES,
        can={Enforcement.CHECK: "biome ci", Enforcement.APPLY: "biome format --write"},
        formats=flagged(
            ("biome", "format"),
            ("biome", "check"),
            ("biome", "ci"),
            applies=("--write", "--apply", "--fix", "--apply-unsafe"),
        ),
        style=defined_by(files=("biome",)),
    ),
    analyzer(
        name="biome",
        languages=JS_LANGUAGES,
        how="biome lint",
        analyses=_analyses(_programs(("biome", "lint"), ("biome", "check"), ("biome", "ci"))),
        rules=defined_by(files=("biome",)),
    ),
)


def _strict(setting: Setting) -> bool:
    """Whether a TypeScript setting turns on strict checking: `"strict": true`, or extending @tsconfig/strictest."""
    if setting.key == "extends":
        return any(_STRICTEST.search(str(base)) for base in _bases(setting.value))
    return setting.key == "compilerOptions.strict" and setting.value is True


def _bases(value: object) -> tuple[object, ...]:
    return value if isinstance(value, tuple) else (value,)


def _tsconfig(command: Command) -> str:
    """The configuration tsc reads: the one `-p`/`--project` names (a file, or a directory holding tsconfig.json), or
    the tsconfig.json where it runs."""
    named = option_values(resolved(command), "-p", "--project", "-b", "--build")
    path = joined(command.directory, named[0]) if named else joined(command.directory, "tsconfig.json")
    return path if path.endswith(".json") else joined(path, "tsconfig.json")


def _strict_settings(path: str, facts: Facts, depth: int = 0) -> list[Setting]:
    """The settings of the configuration `path`, and of the local ones it extends, that make tsc strict."""
    own = facts.settings("TypeScript", paths=[path])
    found = [setting for setting in own if _strict(setting)]
    for setting in own:
        bases = _bases(setting.value) if setting.key == "extends" else ()
        for base in map(str, bases):
            if base.startswith(".") and depth < 4:
                extended = joined(str(PurePosixPath(path).parent), base)
                found += _strict_settings(
                    extended if extended.endswith(".json") else f"{extended}.json", facts, depth + 1
                )
    return found


def _tsc(command: Command, facts: Facts) -> Run | None:
    if not _programs(("tsc",), ("vue-tsc",))(command):
        return None
    strict = _strict_settings(_tsconfig(command), facts)
    return type_checked(strict=bool(strict), read=strict)


def _deno_check(command: Command, facts: Facts) -> Run | None:
    """`deno check`, or `deno test`, which type checks the code it runs; Deno is strict unless told not to."""
    if not _programs(("deno", "check"), ("deno", "test"))(command):
        return None
    lax = facts.setting("Deno", "compilerOptions.strict")
    return type_checked(strict=lax is None or lax.value is not False, read=[lax] if lax else ())


TSC = type_checker(
    name="tsc",
    languages=JS_LANGUAGES,
    can={
        Strictness.CHECKS: "tsc --noEmit (JavaScript is checked with checkJs in a jsconfig.json)",
        Strictness.STRICT: '"strict": true in the compilerOptions of tsconfig.json',
    },
    checks=_tsc,
    configuration=defined_by(settings=("TypeScript",)),
    reads=("TypeScript",),
)
DENO_CHECK = type_checker(
    name="deno check",
    languages=JS_LANGUAGES,
    can={Strictness.CHECKS: "deno check", Strictness.STRICT: "deno check (strict by default)"},
    checks=_deno_check,
    configuration=defined_by(settings=("Deno",)),
    reads=("Deno",),
)

# The eslint rules other practices ask for, matched where eslint reads its configuration, which is code:
# eslint-plugin-security (or Microsoft's SDL rules), and max-lines-per-function, whose options are "off", 0, or
# anything else (a severity, or a severity and its limit).
_SECURITY_PLUGIN = re.compile(r"\beslint-plugin-security\b|@microsoft/eslint-plugin-sdl\b|\bplugin:security/")
_MAX_LINES_PER_FUNCTION = re.compile(
    r"""["']?max-lines-per-function["']?\s*:(?!\s*\[?\s*(?:["']off["']|0\b))""", re.IGNORECASE
)
ESLINT_RULES = SettingsReader(
    name="eslint rules",
    files=(*ESLINT_CONFIG_FILES, PACKAGE_JSON),
    read=lambda path, text: matched_settings(
        "eslint",
        path,
        text,
        {"security plugin": (_SECURITY_PLUGIN, True), "max-lines-per-function": (_MAX_LINES_PER_FUNCTION, True)},
    ),
)


def _eslint_security(command: Command, facts: Facts) -> Run | None:
    if not _programs(("eslint",), ("next", "lint"))(command):
        return None
    read = facts.where(Setting, tool="eslint", key="security plugin")
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(
        name="eslint-plugin-security",
        languages=JS_LANGUAGES,
        how="eslint with eslint-plugin-security",
        scans=_eslint_security,
        reads=("eslint rules",),
    ),
    *multi_language_scanners(JS_LANGUAGES),
)
MAX_LINES_PER_FUNCTION = limiter(
    name="eslint's max-lines-per-function",
    languages=JS_LANGUAGES,
    how="eslint with max-lines-per-function on",
    runs=ESLINT.claims,
    rule=Rule(
        describe="max-lines-per-function on in the eslint configuration",
        enabled=lambda facts: facts.where(Setting, tool="eslint", key="max-lines-per-function"),
    ),
    reads=("eslint rules",),
)
FUNCTION_LENGTH_LIMITERS = (MAX_LINES_PER_FUNCTION, *function_length_limiters(JS_LANGUAGES))
