"""PHP: managed with Composer, judged by the PHP versions CI runs.

PHP projects run their tools through Composer scripts (`composer test`, `composer cs-check`), so the scripts CI runs
count as CI configuration, as package scripts do for JavaScript.
"""

import re
from collections.abc import Callable, Iterator

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import (
    ci_and_hook_texts,
    existing_texts,
    first_existing,
    json_value,
    scripts_run,
)
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import has_option, option_values, positional, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
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
from project_validator.rules import (
    SUGGESTED_LIZARD,
    BuildOutputs,
    DeclaredLicense,
    DependencyManagement,
    Evidence,
    FunctionLimits,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.scanners import multi_language_scanners

PHP_LANGUAGE = "PHP"
PHP_ONLY = frozenset({PHP_LANGUAGE})
COMPOSER_JSON = "composer.json"
COMPOSER = BuildSystem(name="Composer", files=(COMPOSER_JSON,), languages=PHP_ONLY)
PHPUNIT_CONFIG_FILES = ("phpunit.xml", "phpunit.xml.dist", "phpunit.dist.xml")


def _scripts(context: Context) -> dict[str, str]:
    """The Composer scripts, by name; a script of several commands is one command per line."""
    scripts = json_value(context, COMPOSER_JSON, "scripts")
    if not isinstance(scripts, dict):
        return {}
    commands = {name: [value] if isinstance(value, str) else value for name, value in scripts.items()}
    return {
        name: "\n".join(item for item in value if isinstance(item, str))
        for name, value in commands.items()
        if isinstance(value, list)
    }


# `composer test`, `composer run-script lint`, and `@lint` or `@composer lint` inside a script.
CALLS_SCRIPT = re.compile(
    r"\bcomposer\s+(?:run(?:-script)?\s+)?(?P<command>[\w:.-]+)|(?:^|\s)@(?!composer\b|php\b)(?P<script>[\w:.-]+)"
)


def _called(text: str) -> Iterator[str]:
    for match in CALLS_SCRIPT.finditer(text):
        yield match["command"] or match["script"]


def _run_texts(context: Context) -> tuple[str, ...]:
    """CI configuration, pre-commit hooks, and the Composer scripts they run."""
    texts = ci_and_hook_texts(context)
    return (*texts, *scripts_run(texts, _scripts(context), _called))


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


def _with_files(*files: str) -> Evidence:
    """CI configuration, the Composer scripts it runs, and `files`."""

    def texts(context: Context) -> tuple[str, ...]:
        return (*_run_texts(context), *existing_texts(context, files))

    return texts


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


def _required_settings(_: Context) -> tuple[Pattern, ...]:
    return (ERROR_REPORTING,)


# PHP reports notices, warnings and deprecations at run time; the tests must see every one of them.
WARNINGS = WarningPolicy(
    kind="PHP error reporting settings",
    recognised=(ERROR_REPORTING,),
    required=_required_settings,
    texts=_with_files(*PHPUNIT_CONFIG_FILES),
)


def _fails_on(issue: str) -> str:
    return rf"(?:\b{issue}\s*=\s*[\"']true[\"']|--fail-on-{issue.removeprefix('failOn').lower()}\b)"


WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        Pattern(
            "PHPUnit failOnWarning, failOnNotice and failOnDeprecation",
            re.compile(
                rf"(?=[\s\S]*{_fails_on('failOnWarning')})(?=[\s\S]*{_fails_on('failOnNotice')})"
                rf"(?=[\s\S]*{_fails_on('failOnDeprecation')})"
            ),
        ),
        pattern("PHPUnit failOnAllIssues", r"\bfailOnAllIssues\s*=\s*[\"']true[\"']|--fail-on-all-issues\b"),
    ),
    texts=_with_files(*PHPUNIT_CONFIG_FILES),
    searched="phpunit.xml, CI configuration or the Composer scripts it runs",
    hint='set failOnWarning="true", failOnNotice="true" and failOnDeprecation="true" in phpunit.xml',
)


def _required_packages(context: Context) -> tuple[str, ...]:
    tables = (json_value(context, COMPOSER_JSON, table) for table in ("require", "require-dev"))
    return tuple(name for table in tables if isinstance(table, dict) for name in table)


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
RUNS_PHPMD = re.compile(r"(?<![\w-])phpmd\b(?!\.xml)")
# codesize is the PHPMD rule set that has ExcessiveMethodLength.
METHOD_LENGTH_RULES = re.compile(r"\bExcessiveMethodLength\b|\bcodesize\b")


def _method_length_enforced(context: Context) -> Result:
    """PHPMD's ExcessiveMethodLength rule limits method length, when its rule set is used and PHPMD runs."""
    commands = [line for text in _run_texts(context) for line in text.splitlines() if RUNS_PHPMD.search(line)]
    config = first_existing(context, PHPMD_CONFIG_FILES)
    configured = config is not None and METHOD_LENGTH_RULES.search(context.project.read_text(config))
    if commands and (configured or any(map(METHOD_LENGTH_RULES.search, commands))):
        return Result.passed("function length is limited with PHPMD ExcessiveMethodLength")
    if configured:
        return Result.warned(f"ExcessiveMethodLength is enabled in {config} but CI does not run PHPMD")
    return Result.failed(
        "function length is never limited; run PHPMD with its codesize rules (ExcessiveMethodLength) "
        f"or run {SUGGESTED_LIZARD} in CI"
    )


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
PHPMD_FILES = file_reader("PHPMD", PHPMD_CONFIG_FILES)


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


def _declared_dependencies(context: Context) -> str | None:
    packages = [name for name in _required_packages(context) if not PLATFORM_PACKAGE.match(name)]
    return f"declared in {COMPOSER_JSON}" if packages else None


def _composer_lock(context: Context) -> str | None:
    return "composer.lock" if context.committed("composer.lock") else None


def _is_application(context: Context) -> bool:
    """A library's users resolve its dependencies themselves; anything not declared a library locks them."""
    return json_value(context, COMPOSER_JSON, "type") != "library"


DEPENDENCIES = DependencyManagement(
    managed=_declared_dependencies,
    locked=_composer_lock,
    lock_required=_is_application,
    lock_hint="commit composer.lock, so the application is installed with the dependencies it was tested with",
)


def _composer_license(context: Context) -> str | None:
    """Composer's license is an SPDX expression, or a list of licenses to choose from."""
    license_ = json_value(context, COMPOSER_JSON, "license")
    if isinstance(license_, list) and all(isinstance(item, str) for item in license_):
        return " OR ".join(license_) or None
    return license_ if isinstance(license_, str) else None


LICENSE = DeclaredLicense(manifest=COMPOSER_JSON, declared=_composer_license)

VENDOR = BuildOutputs(
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
    rules=(
        versions_axis("PHP version", PHP_LANGUAGE),
        WARNINGS,
        WARNINGS_AS_ERRORS,
        FunctionLimits(without_lizard=_method_length_enforced),
        DEPENDENCIES,
        VENDOR,
        LICENSE,
    ),
)
