"""PHP's tools: what runs its tests, measures coverage, formats, analyses, scans and audits, and the
settings each reads (see `project_validator.facts.tools`)."""

from __future__ import annotations

import re
from collections.abc import Iterator

from project_validator.core import Context
from project_validator.ecosystems.php import COMPOSER_JSON, PHP_ONLY, PHPUNIT_CONFIG_FILES, runs_analyzer
from project_validator.evidence import json_value
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.analysis import analyzer
from project_validator.facts.arguments import has_option, option_values, positional, program, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import (
    SettingsReader,
    file_reader,
    json_settings,
    matched_settings,
    settings,
    xml_root,
)
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either, starts, when
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

# Composer's own commands, which are not script names; `install` and `update` run their event scripts.
_COMPOSER_COMMANDS = frozenset(
    {"require", "remove", "dump-autoload", "dumpautoload", "validate", "show", "outdated", "audit", "config", "exec"}
    | {"global", "init", "create-project", "self-update", "diagnose", "licenses", "depends", "why", "fund"}
)


_EVENTS = {"install": ("pre-install-cmd", "post-install-cmd"), "update": ("pre-update-cmd", "post-update-cmd")}


_CALLBACK = re.compile(r"^[\w\\]+::\w+$")


def _entry_text(entry: str) -> str | None:
    """A script entry as shell text: `@lint` runs the lint script, `@composer` and `@php` run those programs, and a
    PHP callback (`Vendor\\Class::method`) or `@putenv` runs no command."""
    if _CALLBACK.match(entry) or entry.startswith("@putenv"):
        return None
    if entry.startswith("@"):
        name, _, rest = entry[1:].partition(" ")
        return f"{name} {rest}".strip() if name in ("composer", "php") else f"composer run-script {entry[1:]}"
    return entry


def _script_names(words: list[str]) -> tuple[list[str], bool]:
    """The scripts a Composer command runs, and whether it names one explicitly (so that it must exist)."""
    if words[0] in ("run-script", "run"):
        return words[1:2], True
    return list(_EVENTS.get(words[0], words[:1])), False


def _entries(path: str, name: str, value: object) -> Iterator[Script]:
    entries = value if isinstance(value, list) else [value]
    for index, entry in enumerate(entries):
        if isinstance(entry, str) and (text := _entry_text(entry)) is not None:
            at = ("scripts", name, index) if isinstance(value, list) else ("scripts", name)
            yield Script(text=text, origin=Origin(path=path, at=at))


def _composer_scripts(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`composer test`, `composer run-script lint`, `composer install`: the Composer scripts they run."""
    if command.argv[:1] != ("composer",):
        return None
    words, options = positional(command.argv, frozenset({"--working-dir", "-d"}))
    if not words or words[0] in _COMPOSER_COMMANDS:
        return None
    path = joined(options.get("--working-dir") or options.get("-d") or command.directory, COMPOSER_JSON)
    scripts = json_value(context, path, "scripts")
    scripts = scripts if isinstance(scripts, dict) else {}
    names, explicit = _script_names(words)
    if explicit and names and names[0] not in scripts:
        return iter((Unknown(origin=command.origin, subject=f"the script {names[0]}", reason=f"{path} has none"),))
    return (script for name in names if name in scripts for script in _entries(path, name, scripts[name]))


COMPOSER_SCRIPTS = CommandExpander(name="Composer scripts", expand=_composer_scripts)


CS_FIXER_CONFIG_FILES = (".php-cs-fixer.dist.php", ".php-cs-fixer.php")


PHPCS_CONFIG_FILES = ("phpcs.xml", "phpcs.xml.dist", ".phpcs.xml", ".phpcs.xml.dist")


CS_FIXER_FILES = file_reader("PHP-CS-Fixer", CS_FIXER_CONFIG_FILES)


PHPCS_FILES = file_reader("PHP_CodeSniffer", PHPCS_CONFIG_FILES)


PINT_FILES = file_reader("Pint", ("pint.json",))


# Each of them has a default style: PHP-CS-Fixer and PHP_CodeSniffer a PSR one, Pint Laravel's.
PHP_CS_FIXER = format_tool(
    name="PHP-CS-Fixer",
    languages=PHP_ONLY,
    can={Enforcement.CHECK: "php-cs-fixer check", Enforcement.APPLY: "php-cs-fixer fix"},
    formats=flagged(("php-cs-fixer", "fix"), ("php-cs-fixer", "check"), checks=("check", "--dry-run")),
    style=defined_by(files=("PHP-CS-Fixer",)),
)


PHP_CODESNIFFER = format_tool(
    name="PHP_CodeSniffer",
    languages=PHP_ONLY,
    can={Enforcement.CHECK: "phpcs", Enforcement.APPLY: "phpcbf"},
    formats=either(flagged(("phpcs",), applies=()), flagged(("phpcbf",), checks=())),
    style=defined_by(files=("PHP_CodeSniffer",)),
)


PINT = format_tool(
    name="Pint",
    languages=PHP_ONLY,
    can={Enforcement.CHECK: "pint --test", Enforcement.APPLY: "pint"},
    formats=flagged(("pint",), checks=("--test",)),
    style=defined_by(files=("Pint",)),
)


PHP_TEST_FILES = TestFiles(
    name="*Test.php files with PHPUnit test cases or Pest tests",
    languages=PHP_ONLY,
    path=re.compile(r"Test\.php$"),
    contains=re.compile(r"\bextends\s+\\?(?:[\w\\]*\\)?\w*TestCase\b|^\s*(?:test|it|describe)\s*\(", re.MULTILINE),
)


PHP_TESTS = test_runner(
    name="phpunit, pest or composer test",
    languages=PHP_ONLY,
    how="phpunit, pest or composer test",
    runs=lambda command, _facts: tested() if program(resolved(command)) in ("phpunit", "pest", "paratest") else None,
    tests=tests_of(PHP_TEST_FILES.name),
)


_PHPUNIT_PROGRAMS = frozenset({"phpunit", "pest", "paratest"})


_CONFIGURATION_OPTIONS = frozenset({"--configuration", "-c"})


def _read_phpunit_settings(path: str, text: str) -> Iterator[Fact]:
    """The coverage settings of a PHPUnit configuration: `<coverage>`'s attributes, and the reports it writes."""
    root = xml_root("PHPUnit", path, text)
    if isinstance(root, Unknown):
        yield root
        return
    for coverage in root.iter("coverage"):
        yield from settings("PHPUnit", path, ((f"coverage.{name}", value) for name, value in coverage.attrib.items()))
        reports = tuple(child.tag for report in coverage.iter("report") for child in report)
        if reports:
            yield from settings("PHPUnit", path, (("coverage.report", reports),))


def _named_configuration(command: Command) -> list[str]:
    argv = resolved(command)
    if program(argv) not in _PHPUNIT_PROGRAMS:
        return []
    return [joined(command.directory, path) for path in positional(argv, _CONFIGURATION_OPTIONS)[1].values()]


PHPUNIT_SETTINGS = SettingsReader(
    name="PHPUnit", files=PHPUNIT_CONFIG_FILES, read=_read_phpunit_settings, named_by=_named_configuration
)


def _phpunit(command: Command, facts: Facts) -> Run | None:
    """PHPUnit (or Pest, or ParaTest) reporting coverage, from its options or the configuration it reads (the one it
    is given, else the first of phpunit.xml, phpunit.xml.dist and phpunit.dist.xml). It counts branches and paths
    together (with Xdebug), when asked for path coverage; otherwise lines."""
    argv = resolved(command)
    if program(argv) not in _PHPUNIT_PROGRAMS:
        return None
    candidates = _named_configuration(command) or [joined(command.directory, name) for name in PHPUNIT_CONFIG_FILES]
    configuration = facts.first_file("PHPUnit", candidates)
    read = facts.settings("PHPUnit", paths=[configuration]) if configuration else ()
    reports = any(word.startswith("--coverage-") or word == "--coverage" for word in argv)
    if not (reports or any(setting.key == "coverage.report" for setting in read)):
        return None
    configured = any(setting.key == "coverage.pathCoverage" and setting.value == "true" for setting in read)
    path = has_option(argv, "--path-coverage") or configured
    return reported(Granularity.LINE, *((Granularity.BRANCH, Granularity.PATH) if path else ()), read=read)


PHPUNIT = coverage_tool(
    name="PHPUnit",
    languages=PHP_ONLY,
    can={
        Granularity.LINE: "phpunit --coverage-clover",
        Granularity.BRANCH: "phpunit --path-coverage",
        Granularity.PATH: "phpunit --path-coverage",
    },
    measures=_phpunit,
    reads=("PHPUnit",),
)


COMPOSER_REQUIRES = SettingsReader(
    name="Composer",
    files=(COMPOSER_JSON,),
    read=lambda path, text: (
        fact for table in ("require", "require-dev") for fact in json_settings("Composer", path, text, table)
    ),
)


# roave/security-advisories conflicts with every vulnerable version, so Composer refuses to install one.
_INSTALLS = (("composer", "install"), ("composer", "update"), ("composer", "require"))


def _roave(command: Command, facts: Facts) -> Run | None:
    read = facts.where(Setting, tool="Composer", key="roave/security-advisories")
    return audited(read=read) if read and starts(*_INSTALLS)(command) else None


AUDITORS = (
    auditor(
        name="composer audit",
        languages=PHP_ONLY,
        how="composer audit",
        audits=when(starts(("composer", "audit")), audited),
    ),
    auditor(
        name="roave/security-advisories",
        languages=PHP_ONLY,
        how="requiring roave/security-advisories",
        audits=_roave,
        reads=("Composer",),
    ),
    *multi_ecosystem_audits(PHP_ONLY),
)


PSALM_CONFIG_FILES = ("psalm.xml", "psalm.xml.dist")


PHPMD_CONFIG_FILES = ("phpmd.xml", "phpmd.xml.dist", ".phpmd.xml", ".phpmd.xml.dist")


PHPSTAN_CONFIG_FILES = ("phpstan.neon", "phpstan.neon.dist", "phpstan.dist.neon")


_PHPSTAN_LEVEL = re.compile(r"^\s*level:\s*(\w+)\b", re.MULTILINE)


_PSALM_LEVEL = re.compile(r"""\berrorLevel\s*=\s*["'](\d+)["']""")


_TAINT_ANALYSIS = re.compile(r"""\brunTaintAnalysis\s*=\s*["']true["']""")


PHPSTAN_SETTINGS = SettingsReader(
    name="PHPStan",
    files=PHPSTAN_CONFIG_FILES,
    read=lambda path, text: matched_settings("PHPStan", path, text, {"level": (_PHPSTAN_LEVEL, None)}),
)


PSALM_SETTINGS = SettingsReader(
    name="Psalm",
    files=PSALM_CONFIG_FILES,
    read=lambda path, text: matched_settings(
        "Psalm", path, text, {"errorLevel": (_PSALM_LEVEL, None), "runTaintAnalysis": (_TAINT_ANALYSIS, True)}
    ),
)


def _read_phpmd(path: str, text: str) -> Iterator[Fact]:
    """The rules a PHPMD rule set uses (`rulesets/codesize.xml`, or one of its rules), and those it excludes."""
    root = xml_root("PHPMD", path, text)
    if isinstance(root, Unknown):
        yield root
        return
    rules = tuple(rule.get("ref", "") for rule in root.iter("rule"))
    excluded = tuple(exclude.get("name", "") for exclude in root.iter("exclude"))
    yield from settings("PHPMD", path, (("rules", rules), ("excluded", excluded)))


def _phpmd_rule_sets(command: Command) -> list[str]:
    """The rule sets a phpmd command names (`phpmd src text codesize,unusedcode`)."""
    argv = resolved(command)
    words, _ = positional(argv) if program(argv) == "phpmd" else ([], {})
    return words[2].split(",") if len(words) > 2 else []


PHPMD_SETTINGS = SettingsReader(
    name="PHPMD",
    files=PHPMD_CONFIG_FILES,
    read=_read_phpmd,
    named_by=lambda command: [path for path in _phpmd_rule_sets(command) if path.endswith((".xml", ".xml.dist"))],
)


PHPMD = analyzer(
    name="PHPMD", languages=PHP_ONLY, how="phpmd", analyses=runs_analyzer("phpmd"), rules=defined_by(files=("PHPMD",))
)


# codesize is the PHPMD rule set that has ExcessiveMethodLength.
_METHOD_LENGTH_RULES = re.compile(r"\bExcessiveMethodLength\b|\bcodesize\b")


def _excessive_method_length(facts: Facts) -> list[Setting]:
    """The PHPMD rule sets that use ExcessiveMethodLength, and do not exclude it."""
    found = facts.settings("PHPMD")
    excluding = {
        setting.path for setting in found if setting.key == "excluded" and _names("ExcessiveMethodLength", setting)
    }
    return [
        setting
        for setting in found
        if setting.key == "rules"
        and setting.path not in excluding
        and any(_METHOD_LENGTH_RULES.search(str(rule)) for rule in _values(setting))
    ]


def _values(setting: Setting) -> tuple[object, ...]:
    return setting.value if isinstance(setting.value, tuple) else ()


def _names(name: str, setting: Setting) -> bool:
    return name in _values(setting)


EXCESSIVE_METHOD_LENGTH = limiter(
    name="PHPMD's ExcessiveMethodLength",
    languages=PHP_ONLY,
    how="phpmd with its codesize rules (ExcessiveMethodLength)",
    runs=runs_analyzer("phpmd"),
    rule=Rule(
        describe="the codesize rules (ExcessiveMethodLength) in the PHPMD rule set",
        enabled=_excessive_method_length,
        flagged=lambda command: any(map(_METHOD_LENGTH_RULES.search, _phpmd_rule_sets(command))),
    ),
    reads=("PHPMD",),
)


FUNCTION_LENGTH_LIMITERS = (EXCESSIVE_METHOD_LENGTH, *function_length_limiters(PHP_ONLY))


PHAN = analyzer(name="Phan", languages=PHP_ONLY, how="phan", analyses=runs_analyzer("phan"))


_SECURITY_AUDIT = re.compile(r"\bPHPCS_SecurityAudit\b|\bphpcs-security-audit\b")


PHPCS_SECURITY_SETTINGS = SettingsReader(
    name="PHP_CodeSniffer security",
    files=PHPCS_CONFIG_FILES,
    read=lambda path, text: matched_settings(
        "PHP_CodeSniffer", path, text, {"security audit": (_SECURITY_AUDIT, True)}
    ),
)


def _taint_analysis(command: Command, facts: Facts) -> Run | None:
    """Psalm's taint analysis: `psalm --taint-analysis`, or `runTaintAnalysis="true"` in its configuration."""
    argv = resolved(command)
    if not starts_with(argv, ("psalm",)):
        return None
    if "--taint-analysis" in argv:
        return scanned()
    read = facts.where(Setting, tool="Psalm", key="runTaintAnalysis")
    return scanned(read=read) if read else None


def _phpcs_security(command: Command, facts: Facts) -> Run | None:
    """phpcs with the phpcs-security-audit standard: in its configuration, or named by --standard."""
    argv = resolved(command)
    if not starts_with(argv, ("phpcs",)):
        return None
    if any(_SECURITY_AUDIT.search(value) or "Security" in value for value in option_values(argv, "--standard")):
        return scanned()
    read = facts.where(Setting, tool="PHP_CodeSniffer", key="security audit")
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(
        name="Psalm taint analysis",
        languages=PHP_ONLY,
        how="psalm --taint-analysis",
        scans=_taint_analysis,
        reads=("Psalm",),
    ),
    scanner(
        name="phpcs-security-audit",
        languages=PHP_ONLY,
        how="phpcs with phpcs-security-audit",
        scans=_phpcs_security,
        reads=("PHP_CodeSniffer security",),
    ),
    # CodeQL does not analyse PHP.
    *(tool for tool in multi_language_scanners(PHP_ONLY) if tool.name != "CodeQL"),
)
