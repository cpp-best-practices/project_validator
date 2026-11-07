"""The Ruby profile's rules, judged by the generic checks in the Bundler project layout."""

import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems.ruby import BUNDLE, DEPENDENCIES, RUBY
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, run_as, run_in_layout

(
    CODE_FORMATTING,
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
) = checks_named(
    "code-formatting",
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
)
RAKEFILE = {
    "Rakefile": 'require "rubocop/rake_task"\nRSpec::Core::RakeTask.new(:spec)\nRuboCop::RakeTask.new\n'
    "task default: %i[spec rubocop]\n"
}
SPEC = {"spec/app_spec.rb": 'RSpec.describe App do\n  it("adds") { expect(1 + 2).to eq(3) }\nend\n'}

TYPE_HINT = "consider running a type checker in CI: srb tc (Sorbet) or steep check (Steep, with RBS signatures)"
STRICT_HINT = "consider enabling strict mode: # typed: strict files (Sorbet) or D::Ruby.strict in the Steepfile"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RakeTests(unittest.TestCase):
    def test_the_rakefile_counts_when_ci_runs_rake(self) -> None:
        files = {**RAKEFILE, **SPEC, **_ci("bundle exec rake")}
        self.assertEqual(run_as(self, TESTS_RUN, files, RUBY), Result.passed("tests found in 1 file(s)"))
        self.assertEqual(run_as(self, CODE_FORMATTING, files, RUBY), Result.passed("CI enforces the RuboCop style"))
        # Without rake in CI, the Rakefile runs nothing.
        self.assertEqual(
            run_as(self, TESTS_RUN, {**RAKEFILE, **SPEC, **_ci("bundle install")}, RUBY).status, Status.WARN
        )

    def test_tasks_in_rakelib_count_too(self) -> None:
        files = {"rakelib/lint.rake": "require 'standard/rake'\n", **_ci("rake standard")}
        self.assertEqual(run_as(self, CODE_FORMATTING, files, RUBY).status, Status.PASS)

    def test_autocorrecting_enforces_nothing(self) -> None:
        for command in ("rubocop -A", "standardrb --fix"):
            with self.subTest(command=command):
                self.assertEqual(run_as(self, CODE_FORMATTING, _ci(command), RUBY).status, Status.FAIL)
        self.assertEqual(
            run_as(self, CODE_FORMATTING, _ci("bundle exec stree check lib/**/*.rb"), RUBY).status, Status.PASS
        )

    def test_tests_are_specs_or_minitest_files(self) -> None:
        for path in ("spec/models/user_spec.rb", "test/app_test.rb", "test/unit/test_app.rb"):
            with self.subTest(path=path):
                self.assertEqual(run_as(self, TESTS_RUN, {path: "", **_ci("rails test")}, RUBY).status, Status.PASS)
        self.assertEqual(run_as(self, TESTS_RUN, {"lib/app_spec.rb": ""}, RUBY).status, Status.FAIL)


class SettingTests(unittest.TestCase):
    def test_simplecov_must_count_branches(self) -> None:
        branch = {".simplecov": "SimpleCov.start do\n  enable_coverage(:branch)\nend\n"}
        for command in ("bundle exec rake", "bin/rails test", "bundle exec rspec spec/models"):
            with self.subTest(command=command):
                result = run_as(self, COVERAGE, {**branch, **_ci(command)}, RUBY)
                self.assertEqual(result, Result.passed("branch coverage is reported with SimpleCov"))
        # SimpleCov starts when the tests run, and counts lines unless told to count branches too.
        lines = {"spec/spec_helper.rb": 'require "simplecov"\nSimpleCov.start\n', **_ci("bundle exec rspec")}
        for files in (branch, {**branch, **_ci("bundle exec rubocop")}, lines):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, RUBY).status, Status.FAIL)

    def test_ruby_warnings_and_a_linter_are_both_needed(self) -> None:
        for files in (
            _ci("RUBYOPT=-w bundle exec rspec", "bundle exec rubocop"),
            {".rspec": "--warnings\n", **_ci("bundle exec rubocop")},
            {"test/test_helper.rb": "$VERBOSE = true\n", **_ci("standardrb")},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COMPILER_WARNINGS, files, RUBY).status, Status.PASS)
        missing = run_as(self, COMPILER_WARNINGS, _ci("bundle exec rubocop"), RUBY)
        self.assertEqual(missing.message, "missing Ruby warning settings: Ruby warnings")

    def test_method_length_is_limited_by_rubocop_unless_disabled(self) -> None:
        expected = Result.passed("function length is limited with RuboCop's Metrics/MethodLength")
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("bundle exec rubocop --parallel"), RUBY), expected)
        configured = {".rubocop.yml": "Metrics/MethodLength:\n  Max: 20\n"}
        self.assertEqual(
            run_as(self, FUNCTION_LIMITS, {**configured, **_ci("rubocop")}, RUBY),
            Result.passed("function length is limited with RuboCop's Metrics/MethodLength (.rubocop.yml)"),
        )
        self.assertEqual(run_as(self, FUNCTION_LIMITS, configured, RUBY).status, Status.WARN)
        for config in ("Metrics/MethodLength:\n  Enabled: false\n", "Metrics:\n  Enabled: false\n"):
            with self.subTest(config=config):
                files = {".rubocop.yml": config, **_ci("rubocop")}
                self.assertEqual(run_as(self, FUNCTION_LIMITS, files, RUBY).status, Status.FAIL)
        # Standard turns the Metrics cops off.
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("standardrb"), RUBY).status, Status.FAIL)


class SecurityAndTypingTests(unittest.TestCase):
    def test_bundler_audit_audits_the_gems(self) -> None:
        for command in ("bundle audit check --update", "bundle exec bundler-audit"):
            with self.subTest(command=command):
                self.assertEqual(run_as(self, DEPENDENCY_AUDIT, _ci(command), RUBY).status, Status.PASS)

    def test_brakeman_or_rubocop_security_cops(self) -> None:
        result = run_in_layout(self, "Bundler Ruby", SECURITY_SCANNING, _ci("bundle exec brakeman"))
        self.assertEqual(result, Result.passed("CI scans the code for security problems with brakeman"))
        rubocop = run_in_layout(self, "Bundler Ruby", SECURITY_SCANNING, _ci("bundle exec rubocop"))
        self.assertEqual(rubocop, Result.passed("CI scans the code for security problems with RuboCop Security cops"))
        autocorrect = run_in_layout(self, "Bundler Ruby", SECURITY_SCANNING, _ci("bundle exec rubocop -A"))
        self.assertEqual(autocorrect.status, Status.WARN)

    def test_sorbet_or_steep_type_check_and_strict_sigils_are_the_bonus(self) -> None:
        sorbet = {"lib/app.rb": "# typed: strict\nmodule App; end\n", **_ci("bundle exec srb tc")}
        self.assertEqual(
            run_as(self, TYPE_CHECKING_CHECK, sorbet, RUBY),
            Result.passed("Sorbet runs; strict mode bonus: Sorbet (lib/app.rb)"),
        )
        lax = {"Steepfile": "target :lib do\nend\n", **_ci("steep check")}
        self.assertEqual(
            run_as(self, TYPE_CHECKING_CHECK, lax, RUBY),
            Result.passed("Steep (Steepfile) runs", STRICT_HINT),
        )

    def test_reek_is_static_analysis(self) -> None:
        self.assertEqual(run_as(self, STATIC_ANALYSIS, _ci("bundle exec reek"), RUBY), Result.passed("Reek runs"))


class DependencyTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Bundler Ruby", DEPENDENCY_MANAGEMENT, files)

    def test_an_application_locks_its_gems(self) -> None:
        gems = {"Gemfile": 'source "https://rubygems.org"\ngem "rack"\n'}
        self.assertEqual(
            self._run(gems),
            Result.warned("dependencies are declared in Gemfile but not locked", DEPENDENCIES.lock_hint),
        )
        locked = self._run({**gems, "Gemfile.lock": "GEM\n"})
        self.assertEqual(locked, Result.passed("dependencies are declared in Gemfile and locked in Gemfile.lock"))

    def test_a_gem_need_not_lock(self) -> None:
        gemspec = {"app.gemspec": 'Gem::Specification.new { |s| s.add_dependency "rack" }\n'}
        self.assertEqual(self._run(gemspec), Result.passed("dependencies are declared in app.gemspec"))
        self.assertEqual(self._run({}), Result.passed("no dependencies are declared"))

    def test_the_gemspec_licenses_are_a_choice(self) -> None:
        mit = "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        files = {"LICENSE": mit, "app.gemspec": 's.licenses = ["MIT", "Ruby"]\n'}
        result = run_in_layout(self, "Bundler Ruby", LICENSE, files)
        self.assertIn("the gemspec declares MIT OR Ruby", result.details[0])
        self.assertEqual(
            run_in_layout(self, "Bundler Ruby", LICENSE, {**files, "app.gemspec": "s.license = 'MIT'\n"}).status,
            Status.PASS,
        )
        self.assertEqual(
            run_in_layout(self, "Bundler Ruby", LICENSE, {**files, "app.gemspec": "s.licenses = []\n"}).status,
            Status.PASS,
        )
        # A gemspec that names no license declares nothing to compare.
        unnamed = {**files, "app.gemspec": "s.name = 'app'\n"}
        self.assertEqual(run_in_layout(self, "Bundler Ruby", LICENSE, unnamed).status, Status.PASS)

    def test_installed_gems_and_packages_are_outputs(self) -> None:
        self.assertEqual(BUNDLE.artifact(".bundle/config"), ".bundle/")
        self.assertEqual(BUNDLE.artifact("app-0.1.0.gem"), "app-0.1.0.gem")
        self.assertIsNone(BUNDLE.artifact("lib/coverage/report.rb"))

    def test_the_platform_matrix_counts_ruby_versions_and_implementations(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  test:
                    runs-on: ${{ matrix.os }}
                    strategy:
                      matrix:
                        os: [ubuntu-latest, macos-latest]
                        ruby: ["3.4", jruby-10.0]
                    steps:
                      - uses: ruby/setup-ruby@v1
                        with:
                          ruby-version: ${{ matrix.ruby }}
                """
        }
        self.assertIn("2 Ruby version(s) (3.4, jruby-10.0)", run_as(self, PLATFORM_MATRIX, files, RUBY).message)
