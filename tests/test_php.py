"""The PHP profile's rules, judged by the generic checks in the Composer project layout."""

import json
import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems import PHP
from project_validator.ecosystems.php import DEPENDENCIES, TYPE_CHECKING, VENDOR
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, run_as, run_in_layout

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
        self.assertEqual(result, Result.passed("PHP tests found in 1 file(s)"))
        self.assertEqual(
            run_as(self, TESTS_RUN, {"tests/Helper.php": "<?php class Helper extends TestCase {}"}, PHP).status,
            Status.FAIL,
        )

    def test_branch_coverage_needs_path_coverage_which_is_also_the_bonus(self) -> None:
        expected = Result.passed(
            "branch coverage is reported with PHPUnit --path-coverage; path coverage bonus: PHPUnit --path-coverage"
        )
        for files in (
            _ci("vendor/bin/phpunit --coverage-html cov --path-coverage"),
            {"phpunit.xml": '<phpunit><coverage pathCoverage="true"/></phpunit>'},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, PHP), expected)
        # Line coverage (PCOV, or Xdebug without --path-coverage) counts no branches.
        self.assertEqual(run_as(self, COVERAGE, _ci("phpunit --coverage-clover clover.xml"), PHP).status, Status.FAIL)


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
        for files in (_ci("composer audit --locked"), roave):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, DEPENDENCY_AUDIT, files, PHP).status, Status.PASS)
        # A script that CI never runs audits nothing.
        self.assertEqual(run_as(self, DEPENDENCY_AUDIT, _scripts(audit="composer audit"), PHP).status, Status.WARN)

    def test_security_lints_are_taint_analysis_or_phpcs_security_audit(self) -> None:
        for files in (
            {"psalm.xml": '<psalm runTaintAnalysis="true"/>'},
            {"phpcs.xml": '<ruleset><rule ref="PHPCS_SecurityAudit"/></ruleset>'},
            _ci("vendor/bin/psalm --taint-analysis"),
        ):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, "Composer PHP", SECURITY_SCANNING, files).status, Status.PASS)


class AnalysisTests(unittest.TestCase):
    def test_phpmd_codesize_limits_methods_when_phpmd_runs(self) -> None:
        expected = Result.passed("function length is limited with PHPMD ExcessiveMethodLength")
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("vendor/bin/phpmd src text codesize"), PHP), expected)
        config = {"phpmd.xml": '<ruleset><rule ref="rulesets/codesize.xml/ExcessiveMethodLength"/></ruleset>'}
        self.assertEqual(run_as(self, FUNCTION_LIMITS, {**config, **_ci("phpmd src text phpmd.xml")}, PHP), expected)
        warned = run_as(self, FUNCTION_LIMITS, config, PHP)
        self.assertEqual(
            warned, Result.warned("ExcessiveMethodLength is enabled in phpmd.xml but CI does not run PHPMD")
        )
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("phpmd src text cleancode"), PHP).status, Status.FAIL)

    def test_phpstan_or_psalm_type_check_and_a_high_level_is_strict(self) -> None:
        cases = {
            "PHPStan level in phpstan.neon": {"phpstan.neon": "parameters:\n    level: 9\n", **_ci("phpstan")},
            "Psalm errorLevel in psalm.xml": {"psalm.xml": '<psalm errorLevel="1"/>', **_ci("psalm")},
            "phpstan --level": _ci("vendor/bin/phpstan analyse --level=max src"),
        }
        for strict, files in cases.items():
            with self.subTest(strict=strict):
                self.assertIn(f"strict mode bonus: {strict}", run_as(self, TYPE_CHECKING_CHECK, files, PHP).message)
        lax = run_as(self, TYPE_CHECKING_CHECK, {"phpstan.neon": "parameters:\n    level: 5\n", **_ci("phpstan")}, PHP)
        self.assertEqual(lax, Result.passed("PHPStan (phpstan.neon) runs", TYPE_CHECKING.strict_hint))

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
