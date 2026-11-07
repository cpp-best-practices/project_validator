"""PHP: managed with Composer, judged by the PHP versions CI runs.

PHP projects run their tools through Composer scripts (`composer test`, `composer cs-check`), so the scripts CI runs
count as CI configuration, as package scripts do for JavaScript.
"""

import json
import re
from collections.abc import Callable, Iterator

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns
from project_validator.evidence import (
    json_value,
)
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import has_option, option_values, positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import WARNINGS as WARNINGS_PRACTICE
from project_validator.facts.practices import WARNINGS_AS_ERRORS as WARNINGS_AS_ERRORS_PRACTICE
from project_validator.facts.practices import Practice, always, required, requirement_reader
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
from project_validator.facts.tools import Claim, Run, Tool, combined, defined_by, either, starts, when
from project_validator.text import Pattern, pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

PHP_LANGUAGE = "PHP"
PHP_ONLY = frozenset({PHP_LANGUAGE})
COMPOSER_JSON = "composer.json"
COMPOSER = BuildSystem(name="Composer", files=(COMPOSER_JSON,), languages=PHP_ONLY)
PHPUNIT_CONFIG_FILES = ("phpunit.xml", "phpunit.xml.dist", "phpunit.dist.xml")


# `composer test`, `composer run-script lint`, and `@lint` or `@composer lint` inside a script.
CALLS_SCRIPT = re.compile(
    r"\bcomposer\s+(?:run(?:-script)?\s+)?(?P<command>[\w:.-]+)|(?:^|\s)@(?!composer\b|php\b)(?P<script>[\w:.-]+)"
)


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
    return measured(Granularity.LINE, *((Granularity.BRANCH, Granularity.PATH) if path else ()), read=read)


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

# E_ALL & ~E_DEPRECATED leaves some out.
ALL_ERRORS = r"(?:-1|E_ALL)\b(?!\s*(?:&|&amp;|\^|\|))"
ERROR_REPORTING = Pattern(
    "error_reporting = E_ALL",
    re.compile(
        rf"""\berror_reporting["']?\s*(?:[=:,]|value\s*=)\s*["']?{ALL_ERRORS}"""
        rf"""|name\s*=\s*["']error_reporting["']\s+value\s*=\s*["']{ALL_ERRORS}"""
        rf"""|value\s*=\s*["']{ALL_ERRORS}["']\s+name\s*=\s*["']error_reporting["']"""
    ),
)


# PHP reports notices, warnings and deprecations at run time; the tests must see every one of them.
def _fails_on(issue: str) -> str:
    return rf"(?:\b{issue}\s*=\s*[\"']true[\"']|--fail-on-{issue.removeprefix('failOn').lower()}\b)"


_PHP_WARNINGS_AS_ERRORS = (
    required(
        Pattern(
            "PHPUnit failOnWarning, failOnNotice and failOnDeprecation",
            re.compile(
                rf"(?=[\s\S]*{_fails_on('failOnWarning')})(?=[\s\S]*{_fails_on('failOnNotice')})"
                rf"(?=[\s\S]*{_fails_on('failOnDeprecation')})"
            ),
        )
    ),
    required(pattern("PHPUnit failOnAllIssues", r"\bfailOnAllIssues\s*=\s*[\"']true[\"']|--fail-on-all-issues\b")),
)
PHP_WARNING_SETTINGS = requirement_reader(
    "PHPUnit warning settings", PHPUNIT_CONFIG_FILES, (required(ERROR_REPORTING), *_PHP_WARNINGS_AS_ERRORS)
)
# PHP reports notices, warnings and deprecations at run time; the tests must see every one of them.
WARNINGS = Practice(
    name=WARNINGS_PRACTICE,
    languages=PHP_ONLY,
    kind="PHP error reporting settings",
    requirements=always(required(ERROR_REPORTING)),
    reads=(PHP_WARNING_SETTINGS.name,),
    separator=" ",
    hint='set <ini name="error_reporting" value="-1"/> in phpunit.xml',
)


WARNINGS_AS_ERRORS = Practice(
    name=WARNINGS_AS_ERRORS_PRACTICE,
    languages=PHP_ONLY,
    kind="warnings as errors",
    requirements=always(*_PHP_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(PHP_WARNING_SETTINGS.name,),
    searched="phpunit.xml, CI configuration or the Composer scripts it runs",
    hint='set failOnWarning="true", failOnNotice="true" and failOnDeprecation="true" in phpunit.xml',
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
# Strict: PHPStan at level 8 or higher, Psalm at error level 1 or 2.
_STRICT_PHPSTAN = re.compile(r"[89]|1\d|max")
_STRICT_PSALM = frozenset({"1", "2"})

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


def _phpstan_strict(argv: tuple[str, ...], facts: Facts) -> list[Setting] | bool:
    if any(_STRICT_PHPSTAN.fullmatch(level) for level in option_values(argv, "--level", "-l")):
        return True
    return [setting for setting in facts.settings("PHPStan") if _STRICT_PHPSTAN.fullmatch(str(setting.value))]


def _psalm_strict(_argv: tuple[str, ...], facts: Facts) -> list[Setting] | bool:
    return [setting for setting in facts.settings("Psalm") if str(setting.value) in _STRICT_PSALM]


type _Strict = Callable[[tuple[str, ...], Facts], list[Setting] | bool]


def _runs(name: str) -> Callable[[Command, Facts], Run | None]:
    return lambda command, _facts: analysed() if program(resolved(command)) == name else None


def _type_checks(name: str, strict: _Strict) -> Claim:
    def checks(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if program(argv) != name:
            return None
        found = strict(argv, facts)
        return type_checked(strict=bool(found), read=found if isinstance(found, list) else ())

    return checks


def _analyser_and_checker(name: str, strict: _Strict, how: str, strict_how: str) -> Tool:
    """PHPStan or Psalm: a run analyses the code and type checks it, strictly at a strict level."""
    command = name.lower()
    definition = defined_by(files=(name,), settings=(name,))
    return combined(
        analyzer(name=name, languages=PHP_ONLY, how=how, analyses=_runs(command), rules=definition, reads=(name,)),
        type_checker(
            name=name,
            languages=PHP_ONLY,
            can={Strictness.CHECKS: how, Strictness.STRICT: strict_how},
            checks=_type_checks(command, strict),
            configuration=definition,
            reads=(name,),
        ),
    )


PHPSTAN = _analyser_and_checker("PHPStan", _phpstan_strict, "phpstan analyse", "level: 8 (or max) in phpstan.neon")
PSALM = _analyser_and_checker("Psalm", _psalm_strict, "psalm", 'errorLevel="2" in psalm.xml')
PHPMD = analyzer(
    name="PHPMD", languages=PHP_ONLY, how="phpmd", analyses=_runs("phpmd"), rules=defined_by(files=("PHPMD",))
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
    runs=_runs("phpmd"),
    rule=Rule(
        describe="the codesize rules (ExcessiveMethodLength) in the PHPMD rule set",
        enabled=_excessive_method_length,
        flagged=lambda command: any(map(_METHOD_LENGTH_RULES.search, _phpmd_rule_sets(command))),
    ),
    reads=("PHPMD",),
)
FUNCTION_LENGTH_LIMITERS = (EXCESSIVE_METHOD_LENGTH, *function_length_limiters(PHP_ONLY))
PHAN = analyzer(name="Phan", languages=PHP_ONLY, how="phan", analyses=_runs("phan"))

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
    if program(argv) != "psalm":
        return None
    if "--taint-analysis" in argv:
        return scanned()
    read = facts.where(Setting, tool="Psalm", key="runTaintAnalysis")
    return scanned(read=read) if read else None


def _phpcs_security(command: Command, facts: Facts) -> Run | None:
    """phpcs with the phpcs-security-audit standard: in its configuration, or named by --standard."""
    argv = resolved(command)
    if program(argv) != "phpcs":
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

# The platform (php, ext-*, lib-*) is not a package Composer installs.
PLATFORM_PACKAGE = re.compile(r"^(?:php|php-64bit|hhvm|composer(?:-plugin|-runtime)?-api|(?:ext|lib)-.+)$")


def _composer(text: str) -> dict[str, object]:
    manifest = json.loads(text)
    return manifest if isinstance(manifest, dict) else {}


def _composer_declares(_path: str, text: str) -> bool:
    """composer.json requires packages beyond the platform (PHP itself, its extensions)."""
    manifest = _composer(text)
    tables = (manifest.get(table) for table in ("require", "require-dev"))
    packages = (name for table in tables if isinstance(table, dict) for name in table)
    return any(not PLATFORM_PACKAGE.match(name) for name in packages)


COMPOSER_DEPENDENCIES = manifest_reader(
    name="Composer dependencies",
    manager="Composer",
    files=(COMPOSER_JSON,),
    declares=_composer_declares,
    library=lambda _path, text: _composer(text).get("type") == "library",
)
COMPOSER_LOCK = lockfile_reader(manager="Composer", files=("composer.lock",))
# A library's users resolve its dependencies themselves; anything not declared a library locks them.
COMPOSER_PACKAGES = PackageManager(
    name="Composer",
    languages=PHP_ONLY,
    lock=Lock.APPLICATIONS,
    lock_hint="commit composer.lock, so the application is installed with the dependencies it was tested with",
)


def _composer_license(text: str) -> str | None:
    """Composer's license is an SPDX expression, or a list of licenses to choose from."""
    license_ = _composer(text).get("license")
    if isinstance(license_, list) and all(isinstance(item, str) for item in license_):
        return " OR ".join(license_) or None
    return license_ if isinstance(license_, str) else None


COMPOSER_LICENSE = declared_license_reader(
    name="composer.json license", files=(COMPOSER_JSON,), languages=PHP_ONLY, declared=_composer_license
)

VENDOR = BuildOutput(
    languages=PHP_ONLY,
    name="vendor",
    globs=ignored_at_top_level("vendor"),
    paths=directories("vendor"),
    hint="consider ignoring /vendor/ (and .phpunit.cache/ or .phpunit.result.cache)",
    artifacts=("/vendor/", ".phpunit.cache/", ".phpunit.result.cache"),
)

_PHP_VERSION = r"(\d+\.\d+)"

PHP = Ecosystem(
    label="PHP",
    languages=PHP_ONLY,
    build_systems=(COMPOSER,),
    source_suffixes={".php": PHP_LANGUAGE},
    toolchain=ToolchainPatterns(
        language=PHP_LANGUAGE,
        versions=(re.compile(rf"\bphp-version\W+{_PHP_VERSION}"), re.compile(rf"\bphp:{_PHP_VERSION}")),
        usage=re.compile(r"\bcomposer\s+(?:install|update|test|run|audit)\b|\bsetup-php\b|\bvendor/bin/|\bphp\s+-"),
    ),
)

PHP_VERSIONS = versions_axis("PHP version", PHP_LANGUAGE, PHP_ONLY)
