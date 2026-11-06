"""PHP: managed with Composer, judged by the PHP versions CI runs.

PHP projects run their tools through Composer scripts (`composer test`, `composer cs-check`), so the scripts CI runs
count as CI configuration, as package scripts do for JavaScript.
"""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import (
    ci_and_hook_texts,
    configuration,
    existing_texts,
    first_existing,
    json_value,
    scripts_run,
)
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined, positional
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    CoverageTools,
    DeclaredLicense,
    DependencyAudit,
    DependencyManagement,
    Evidence,
    Formatter,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    TypeChecking,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, pattern

PHP_LANGUAGE = "PHP"
COMPOSER_JSON = "composer.json"
COMPOSER = BuildSystem(name="Composer", files=(COMPOSER_JSON,), languages=frozenset({PHP_LANGUAGE}))
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

# Each of them has a default style: PHP-CS-Fixer and PHP_CodeSniffer a PSR one, Pint Laravel's.
FORMATTERS = Formatter(
    name="PHP-CS-Fixer, PHP_CodeSniffer or Pint",
    config_file=configuration((*CS_FIXER_CONFIG_FILES, *PHPCS_CONFIG_FILES, "pint.json")),
    runs=(
        pattern("PHP-CS-Fixer", r"\bphp-cs-fixer\b[^\n]*(?:\bcheck\b|--dry-run\b)"),
        pattern("PHP_CodeSniffer", r"(?<![\w-])phpcs\b(?!\.xml)"),
        pattern("Pint", r"\bpint\b[^\n]*\s--test\b"),
    ),
    hint="consider a CI job that runs php-cs-fixer check (or phpcs, or pint --test)",
    default_style=True,
    texts=_run_texts,
)

TEST_CASE = re.compile(r"\bextends\s+\\?(?:[\w\\]*\\)?\w*TestCase\b|^\s*(?:test|it|describe)\s*\(", re.MULTILINE)
RUNS_TESTS = (
    pattern(
        "PHP tests",
        r"(?<![\w-])(?:phpunit|pest|paratest)\b(?!\.xml)|\bcomposer\s+(?:run(?:-script)?\s+)?tests?\b",
    ),
)


def _php_tests(context: Context) -> Result:
    tests = (path for path in context.project.files() if PurePosixPath(path).name.endswith("Test.php"))
    count = sum(1 for path in tests if TEST_CASE.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no PHP tests found (*Test.php files with PHPUnit test cases or Pest tests)")
    return Result.passed(f"PHP tests found in {count} file(s)")


TESTS = TestSuite(found=_php_tests, runs=RUNS_TESTS, runner="phpunit, pest or composer test", texts=_run_texts)

# PHPUnit collects branch and path coverage together (with Xdebug); line coverage alone counts no branches.
PATH_COVERAGE = pattern("PHPUnit --path-coverage", r"--path-coverage\b|\bpathCoverage\s*=\s*[\"']true[\"']")
COVERAGE = CoverageTools(
    searched="CI configuration, the Composer scripts it runs, or phpunit.xml",
    texts=_with_files(*PHPUNIT_CONFIG_FILES),
    branch=(PATH_COVERAGE,),
    path=(PATH_COVERAGE,),
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


def _audit_texts(context: Context) -> tuple[str, ...]:
    return (*_run_texts(context), "\n".join(_required_packages(context)))


DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        pattern("composer audit", r"\bcomposer\s+audit\b"),
        # It conflicts with every vulnerable version, so Composer refuses to install one.
        pattern("roave/security-advisories", r"\broave/security-advisories\b"),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="consider running composer audit in CI (or requiring roave/security-advisories)",
    texts=_audit_texts,
)

PSALM_CONFIG_FILES = ("psalm.xml", "psalm.xml.dist")


def _security_texts(context: Context) -> tuple[str, ...]:
    files = existing_texts(context, (*PSALM_CONFIG_FILES, *PHPCS_CONFIG_FILES))
    return (*_audit_texts(context), *files)


SECURITY_LINTS = SecurityLints(
    texts=_security_texts,
    lints=(
        pattern("Psalm taint analysis", r"\bpsalm\b[^\n]*--taint-analysis\b|\brunTaintAnalysis\s*=\s*[\"']true"),
        pattern("phpcs-security-audit", r"\bphpcs-security-audit\b|\bPHPCS_SecurityAudit\b"),
    ),
)

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
PHPSTAN = Analyzer(
    name="PHPStan", runs=re.compile(r"\bphpstan\b(?!\.neon)"), configured=configuration(PHPSTAN_CONFIG_FILES)
)
PSALM = Analyzer(
    name="Psalm", runs=re.compile(r"(?<![\w-])psalm\b(?!\.xml)"), configured=configuration(PSALM_CONFIG_FILES)
)

STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        PHPSTAN,
        PSALM,
        Analyzer(name="PHPMD", runs=RUNS_PHPMD, configured=configuration(PHPMD_CONFIG_FILES)),
        Analyzer(name="Phan", runs=re.compile(r"(?<![\w-])phan\b")),
    ),
    texts=_run_texts,
    hint="consider running PHPStan or Psalm (or PHPMD, or Phan) in CI",
)

STRICT_PHPSTAN_LEVEL = re.compile(r"^\s*level:\s*(?:[89]|1\d|max)\b", re.MULTILINE)
STRICT_PHPSTAN_FLAG = re.compile(r"\bphpstan\b[^\n]*\s(?:--level[=\s]+|-l\s*)(?:[89]|1\d|max)\b")
STRICT_PSALM_LEVEL = re.compile(r"""\berrorLevel\s*=\s*["'][12]["']""")


def _strict_type_checking(context: Context) -> str | None:
    """PHPStan at level 8 or higher, or Psalm at error level 1 or 2."""
    for files, strict, name in (
        (PHPSTAN_CONFIG_FILES, STRICT_PHPSTAN_LEVEL, "PHPStan level"),
        (PSALM_CONFIG_FILES, STRICT_PSALM_LEVEL, "Psalm errorLevel"),
    ):
        config = first_existing(context, files)
        if config is not None and strict.search(context.project.read_text(config)):
            return f"{name} in {config}"
    return "phpstan --level" if any(map(STRICT_PHPSTAN_FLAG.search, _run_texts(context))) else None


TYPE_CHECKING = TypeChecking(
    checkers=(PHPSTAN, PSALM),
    texts=_run_texts,
    strict=_strict_type_checking,
    hint="consider running PHPStan (or Psalm) in CI",
    strict_hint='consider a strict level: level: 8 (or max) in phpstan.neon, or errorLevel="2" in psalm.xml',
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
    languages=frozenset({PHP_LANGUAGE}),
    build_systems=(COMPOSER,),
    source_suffixes={".php": PHP_LANGUAGE},
    toolchain=ToolchainPatterns(
        language=PHP_LANGUAGE,
        versions=(re.compile(rf"\bphp-version\W+{_PHP_VERSION}"), re.compile(rf"\bphp:{_PHP_VERSION}")),
        usage=re.compile(r"\bcomposer\s+(?:install|update|test|run|audit)\b|\bsetup-php\b|\bvendor/bin/|\bphp\s+-"),
    ),
    rules=(
        versions_axis("PHP version", PHP_LANGUAGE),
        FORMATTERS,
        COVERAGE,
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_method_length_enforced),
        STATIC_ANALYSIS,
        TYPE_CHECKING,
        DEPENDENCIES,
        VENDOR,
        LICENSE,
    ),
)
