"""The PHP profile's rules, judged by the generic checks in the Composer project layout."""

import json
import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems.php import DEPENDENCIES, PHP, VENDOR
from project_validator.facts import Command, Facts, Unknown
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, make_context, run_as, run_in_layout, temp_project

(
    CODE_FORMATTING,
    COMMITTED_ARTIFACTS,
    COMPILER_WARNINGS,
    COVERAGE,
    DEPENDENCY_AUDIT,
    DEPENDENCY_MANAGEMENT,
    FUNCTION_LIMITS,
    LICENSE,
    PLATFORM_MATRIX,
    SECURITY_SCANNING,
    STATIC_ANALYSIS,
    TESTS_RUN,
    TYPE_CHECKING_CHECK,
    WARNINGS_AS_ERRORS,
) = checks_named(
    "code-formatting",
    "committed-artifacts",
    "compiler-warnings",
    "coverage",
    "dependency-audit",
    "dependency-management",
    "function-limits",
    "license",
    "platform-matrix",
    "security-scanning",
    "static-analysis",
    "tests-run",
    "type-checking",
    "warnings-as-errors",
)
SETUP_PHP_INI = "steps:\n  - uses: shivammathur/setup-php@v2\n    with:\n      ini-values: error_reporting=E_ALL\n"
PHPUNIT_TEST = {"tests/AppTest.php": "<?php\nfinal class AppTest extends \\PHPUnit\\Framework\\TestCase {}\n"}

TYPE_HINT = "consider running a type checker in CI: phpstan analyse or psalm"
STRICT_HINT = 'consider enabling strict mode: level: 8 (or max) in phpstan.neon or errorLevel="2" in psalm.xml'


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _composer(**fields: object) -> dict[str, str]:
    return {"composer.json": json.dumps(fields)}


def _scripts(**scripts: str | list[str]) -> dict[str, str]:
    return _composer(scripts=scripts)


class ComposerScriptTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, CODE_FORMATTING, files, PHP)

    def test_scripts_ci_runs_count_as_ci(self) -> None:
        for files in (
            {**_scripts(cs="php-cs-fixer fix --dry-run --diff"), **_ci("composer cs")},
            {**_scripts(check=["@lint", "@cs"], lint="phpstan", cs="phpcs"), **_ci("composer run-script check")},
            {**_scripts(ci="@composer style", style="pint --test"), **_ci("composer run ci")},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files).status, Status.PASS)

    def test_scripts_ci_never_runs_and_fixing_do_not_count(self) -> None:
        self.assertEqual(self._run(_scripts(cs="php-cs-fixer check")).status, Status.FAIL)
        self.assertEqual(self._run(_ci("vendor/bin/php-cs-fixer fix", "phpcbf")).status, Status.FAIL)
        self.assertEqual(self._run({"composer.json": '{"scripts": "not a table"}'}).status, Status.FAIL)
        self.assertEqual(self._run({"phpcs.xml.dist": "<ruleset/>"}).status, Status.WARN)


class TestAndCoverageTests(unittest.TestCase):
    def test_tests_are_phpunit_test_cases_or_pest_tests(self) -> None:
        pest = {"tests/Unit/AddTest.php": "<?php\n\nit('adds', fn () => expect(1 + 2)->toBe(3));\n"}
        for files in (PHPUNIT_TEST, pest):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, TESTS_RUN, {**files, **_ci("vendor/bin/pest")}, PHP).status, Status.PASS)
        result = run_as(self, TESTS_RUN, {**PHPUNIT_TEST, **_scripts(test="phpunit"), **_ci("composer test")}, PHP)
        self.assertEqual(result, Result.passed("tests found in 1 file(s)"))
        self.assertEqual(
            run_as(self, TESTS_RUN, {"tests/Helper.php": "<?php class Helper extends TestCase {}"}, PHP).status,
            Status.FAIL,
        )

    def test_branch_coverage_needs_path_coverage_which_is_also_the_bonus(self) -> None:
        expected = Result.passed("branch coverage is reported with PHPUnit; path coverage bonus: PHPUnit")
        configured = {
            "phpunit.xml.dist": '<phpunit><coverage pathCoverage="true"><report><clover/></report></coverage></phpunit>'
        }
        for files in (
            _ci("vendor/bin/phpunit --coverage-html cov --path-coverage"),
            {**configured, **_ci("vendor/bin/phpunit")},
            {"ci.xml": configured["phpunit.xml.dist"], **_ci("phpunit -c ci.xml")},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, PHP), expected)
        # Line coverage (PCOV, or Xdebug without --path-coverage) counts no branches; settings count only when CI runs
        # PHPUnit, and only once a report is asked for.
        unreported = {"phpunit.xml": '<phpunit><coverage pathCoverage="true"/></phpunit>', **_ci("phpunit")}
        for files in (_ci("phpunit --coverage-clover clover.xml"), configured, unreported):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, PHP).status, Status.FAIL)


class WarningTests(unittest.TestCase):
    def test_every_error_must_be_reported_while_testing(self) -> None:
        for files in (
            {"phpunit.xml.dist": '<php><ini name="error_reporting" value="E_ALL"/></php>'},
            {"phpunit.xml": "<php><ini value='-1' name='error_reporting'/></php>"},
            _ci("php -d error_reporting=-1 vendor/bin/phpunit"),
            {GITHUB_WORKFLOW: SETUP_PHP_INI},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COMPILER_WARNINGS, files, PHP).status, Status.PASS)
        partial = {"phpunit.xml": '<ini name="error_reporting" value="E_ALL &amp; ~E_DEPRECATED"/>'}
        self.assertEqual(run_as(self, COMPILER_WARNINGS, partial, PHP).status, Status.FAIL)
        self.assertEqual(run_as(self, COMPILER_WARNINGS, {"phpunit.xml": "<phpunit/>"}, PHP).status, Status.FAIL)

    def test_phpunit_must_fail_on_warnings_notices_and_deprecations(self) -> None:
        every = _ci("phpunit --fail-on-warning --fail-on-notice --fail-on-deprecation")
        for files in (every, {"phpunit.xml": '<phpunit failOnAllIssues="true"/>'}):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, files, PHP).status, Status.PASS)
        some = {"phpunit.xml": '<phpunit failOnWarning="true" failOnNotice="true"/>'}
        self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, some, PHP).status, Status.FAIL)


class SecurityTests(unittest.TestCase):
    def test_composer_audit_or_roave_security_advisories(self) -> None:
        roave = _composer(**{"require-dev": {"roave/security-advisories": "dev-latest"}})
        for files in (_ci("composer audit --locked"), {**roave, **_ci("composer install")}):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, DEPENDENCY_AUDIT, files, PHP).status, Status.PASS)
        # roave/security-advisories stops Composer installing a vulnerable version; it acts where CI installs.
        self.assertEqual(run_as(self, DEPENDENCY_AUDIT, roave, PHP).status, Status.WARN)
        # A script that CI never runs audits nothing.
        self.assertEqual(run_as(self, DEPENDENCY_AUDIT, _scripts(audit="composer audit"), PHP).status, Status.WARN)

    def test_security_lints_are_taint_analysis_or_phpcs_security_audit(self) -> None:
        taint = {"psalm.xml": '<psalm runTaintAnalysis="true"/>'}
        audit = {"phpcs.xml": '<ruleset><rule ref="PHPCS_SecurityAudit"/></ruleset>'}
        for files in (
            {**taint, **_ci("vendor/bin/psalm")},
            {**audit, **_ci("vendor/bin/phpcs")},
            _ci("vendor/bin/psalm --taint-analysis"),
            _ci("vendor/bin/phpcs --standard=Security src"),
        ):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, "Composer PHP", SECURITY_SCANNING, files).status, Status.PASS)
        # The settings count where CI runs the tool.
        for files in (taint, audit, _ci("vendor/bin/phpcs src")):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, "Composer PHP", SECURITY_SCANNING, files).status, Status.WARN)


class AnalysisTests(unittest.TestCase):
    def test_phpmd_codesize_limits_methods_when_phpmd_runs(self) -> None:
        expected = Result.passed("function length is limited with PHPMD's ExcessiveMethodLength")
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("vendor/bin/phpmd src text codesize"), PHP), expected)
        config = {"phpmd.xml": '<ruleset><rule ref="rulesets/codesize.xml/ExcessiveMethodLength"/></ruleset>'}
        self.assertEqual(
            run_as(self, FUNCTION_LIMITS, {**config, **_ci("phpmd src text phpmd.xml")}, PHP),
            Result.passed("function length is limited with PHPMD's ExcessiveMethodLength (phpmd.xml)"),
        )
        # A rule set named on the command line is read too.
        custom = {"build/rules.xml": '<ruleset><rule ref="rulesets/codesize.xml"/></ruleset>'}
        self.assertEqual(
            run_as(self, FUNCTION_LIMITS, {**custom, **_ci("phpmd src text build/rules.xml")}, PHP).status, Status.PASS
        )
        warned = run_as(self, FUNCTION_LIMITS, config, PHP)
        self.assertEqual(
            warned.message, "phpmd.xml limits function length, but CI does not run PHPMD's ExcessiveMethodLength"
        )
        excluded = '<ruleset><rule ref="rulesets/codesize.xml"><exclude name="ExcessiveMethodLength"/></rule></ruleset>'
        for files in (
            _ci("phpmd src text cleancode"),
            {"phpmd.xml": excluded, **_ci("phpmd src text phpmd.xml")},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, FUNCTION_LIMITS, files, PHP).status, Status.FAIL)
        unreadable = {"phpmd.xml": "<ruleset", **_ci("phpmd src text phpmd.xml")}
        self.assertEqual(run_as(self, FUNCTION_LIMITS, unreadable, PHP).status, Status.ERROR)

    def test_phpstan_or_psalm_type_check_and_a_high_level_is_strict(self) -> None:
        cases = {
            "PHPStan (phpstan.neon)": {"phpstan.neon": "parameters:\n    level: 9\n", **_ci("phpstan")},
            "Psalm (psalm.xml)": {"psalm.xml": '<psalm errorLevel="1"/>', **_ci("psalm")},
            "PHPStan": _ci("vendor/bin/phpstan analyse --level=max src"),
        }
        for strict, files in cases.items():
            with self.subTest(strict=strict):
                self.assertIn(f"strict mode bonus: {strict}", run_as(self, TYPE_CHECKING_CHECK, files, PHP).message)
        lax = run_as(self, TYPE_CHECKING_CHECK, {"phpstan.neon": "parameters:\n    level: 5\n", **_ci("phpstan")}, PHP)
        self.assertEqual(lax, Result.passed("PHPStan (phpstan.neon) runs", STRICT_HINT))

    def test_any_analyzer_counts_as_static_analysis(self) -> None:
        self.assertEqual(run_as(self, STATIC_ANALYSIS, _ci("vendor/bin/phan"), PHP), Result.passed("Phan runs"))
        self.assertEqual(run_as(self, STATIC_ANALYSIS, _ci("composer install"), PHP).status, Status.FAIL)


class DependencyTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Composer PHP", DEPENDENCY_MANAGEMENT, files)

    def test_an_application_locks_its_dependencies(self) -> None:
        declared = _composer(require={"php": ">=8.3", "ext-json": "*", "psr/log": "^3"})
        expected = Result.warned("dependencies are declared in composer.json but not locked", DEPENDENCIES.lock_hint)
        self.assertEqual(self._run(declared), expected)
        locked = self._run({**declared, "composer.lock": "{}"})
        self.assertEqual(
            locked, Result.passed("dependencies are declared in composer.json and locked in composer.lock")
        )

    def test_a_library_need_not_lock_and_the_platform_is_no_dependency(self) -> None:
        library = _composer(type="library", require={"psr/log": "^3"})
        self.assertEqual(self._run(library), Result.passed("dependencies are declared in composer.json"))
        platform = _composer(require={"php": ">=8.3", "ext-mbstring": "*"})
        self.assertEqual(self._run(platform), Result.passed("no dependencies are declared"))

    def test_a_list_of_licenses_is_a_choice(self) -> None:
        mit = "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        files = {"LICENSE": mit, **_composer(license=["MIT", "GPL-3.0-or-later"])}
        result = run_in_layout(self, "Composer PHP", LICENSE, files)
        self.assertIn("composer.json declares MIT OR GPL-3.0-or-later", result.details[0])
        self.assertEqual(
            run_in_layout(self, "Composer PHP", LICENSE, {**files, **_composer(license=["MIT"])}).status, Status.PASS
        )


class OutputTests(unittest.TestCase):
    def test_vendor_and_phpunit_caches_are_outputs(self) -> None:
        result = run_as(self, COMMITTED_ARTIFACTS, {".phpunit.result.cache": "{}"}, PHP)
        self.assertEqual(result.message, "1 build output is committed")
        # Only git, not a walk of the files, sees committed hidden directories.
        self.assertEqual(VENDOR.artifact(".phpunit.cache/test-results"), ".phpunit.cache/")
        self.assertEqual(VENDOR.artifact("vendor/psr/log/composer.json"), "vendor/")
        self.assertIsNone(VENDOR.artifact("src/vendor/x.php"))

    def test_the_platform_matrix_counts_php_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  linux:
                    runs-on: ubuntu-latest
                    container: php:8.4-cli
                    steps:
                      - run: composer install
                  windows:
                    runs-on: windows-latest
                    steps:
                      - uses: shivammathur/setup-php@v2
                        with:
                          php-version: "8.3"
                """
        }
        self.assertIn("2 PHP version(s) (8.3, 8.4)", run_as(self, PLATFORM_MATRIX, files, PHP).message)


SCRIPTS: dict[str, str | list[str]] = {
    "test": ["@lint", "phpunit --path-coverage", "App\\Tests\\Hooks::after", "@putenv XDEBUG_MODE=coverage"],
    "lint": "@php vendor/bin/phpstan analyse",
    "post-install-cmd": "@composer dump-autoload",
}


class ScriptExpansionTests(unittest.TestCase):
    """The Composer scripts a CI command runs are commands of the job too."""

    def _facts(self, *steps: str) -> Facts:
        with temp_project({**_scripts(**SCRIPTS), **github_job("ubuntu-latest", *steps)}) as root:
            return make_context(root).facts

    def test_a_script_runs_its_commands_and_the_scripts_it_names(self) -> None:
        for step in ("composer test", "composer run-script test", "composer run test"):
            with self.subTest(step=step):
                expanded = [command.argv for command in self._facts(step).of(Command) if command.via]
                self.assertEqual(
                    expanded,
                    [
                        ("composer", "run-script", "lint"),
                        ("php", "vendor/bin/phpstan", "analyse"),
                        ("phpunit", "--path-coverage"),
                    ],
                )

    def test_install_runs_its_event_scripts(self) -> None:
        expanded = [command.argv for command in self._facts("composer install").of(Command) if command.via]
        self.assertEqual(expanded, [("composer", "dump-autoload")])

    def test_composer_commands_are_not_scripts_and_a_missing_script_is_unknown(self) -> None:
        facts = self._facts("composer validate --strict", "composer run-script deploy")
        self.assertEqual([command.argv for command in facts.of(Command) if command.via], [])
        self.assertEqual([fact.subject for fact in facts.of(Unknown)], ["the script deploy"])
