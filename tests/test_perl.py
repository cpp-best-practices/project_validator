"""The Perl profile's rules, judged by the generic checks in the MakeMaker distribution and plain modules layouts."""

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.perl import PERL_ECOSYSTEM, PERL_MODULES
from project_validator.facts import Setting
from tests.support import GITHUB_WORKFLOW, github_job, make_context, run_as, run_in_layout, temp_project

PERL = frozenset({"Perl"})
TEST = {"t/shop.t": "use Test::More;\nok(1, 'works');\ndone_testing;\n"}
STRICT = "package Shop;\nuse strict;\nuse warnings;\n1;\n"
PERL_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest]
            perl: ["5.38", "5.40"]
        steps:
          - uses: shogo82148/actions-setup-perl@v1
            with:
              perl-version: ${{ matrix.perl }}
          - run: prove -l t
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _pragmas(text: str) -> dict[str, object]:
    return {
        setting.key: setting.value for setting in PERL_MODULES.read("lib/Shop.pm", text) if isinstance(setting, Setting)
    }


class RecognitionTests(unittest.TestCase):
    def test_modules_and_the_distributions_build_files(self) -> None:
        with temp_project({"lib/Shop.pm": STRICT, "bin/shop.pl": "", "t/shop.t": "", "lib/Shop.pod": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (PERL, frozenset()))
        self.assertEqual(structure.unrecognised_suffixes, ())
        # A .pl file alone may be Prolog.
        with temp_project({"family.pl": "parent(tom, bob).\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())
        files = {"Build.PL": "", "dist.ini": "", "cpanfile": "", "lib/Shop.pm": STRICT}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.build_systems, frozenset({"Module::Build", "Dist::Zilla", "cpanfile"}))

    def test_the_pragmas_a_module_starts_with(self) -> None:
        self.assertEqual(_pragmas(STRICT), {"strict": True, "warnings": True})
        self.assertEqual(_pragmas("package Shop;\nuse strict;\n1;\n"), {"strict": True, "warnings": False})
        self.assertEqual(_pragmas("package Shop;\nuse Moose;\n1;\n"), {"strict": True, "warnings": True})
        self.assertEqual(_pragmas("use v5.36;\npackage Shop;\n1;\n"), {"strict": True, "warnings": True})
        self.assertEqual(_pragmas("use v5.12;\npackage Shop;\n1;\n"), {"strict": True, "warnings": False})
        self.assertEqual(_pragmas("package Shop;\n1;\n"), {"strict": False, "warnings": False})

    def test_ci_usage(self) -> None:
        for text in ("prove -l t", "cpanm --installdeps .", "uses: shogo82148/actions-setup-perl@v1", "cover -test"):
            with self.subTest(text=text):
                self.assertTrue(PERL_ECOSYSTEM.used_by(text))
        self.assertFalse(PERL_ECOSYSTEM.used_by("npm test"))


class PerlTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, PERL_ECOSYSTEM)

    def test_the_test_runners_run_the_t_files(self) -> None:
        for line in ("prove -lv t", "make test", "./Build test", "dzil test", "cover -test", "yath test"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TEST, **_ci(line)}).status, Status.PASS)
        test2 = {"t/shop.t": "use Test2::V0;\nis(1, 1);\ndone_testing;\n", **_ci("prove -l t")}
        self.assertEqual(self._run(tests_run, test2).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TEST, **_ci("perl Makefile.PL")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("prove -l t")).status, Status.FAIL)

    def test_devel_cover_counts_branches_and_conditions(self) -> None:
        for files in (
            _ci("cover -test"),
            _ci("prove -l t", "cover -report codecov"),
            github_job("ubuntu-latest", "HARNESS_PERL_SWITCHES=-MDevel::Cover prove -l t"),
        ):
            with self.subTest(files=files):
                result = self._run(coverage, files)
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("branch coverage is reported with Devel::Cover", result.message)
        self.assertEqual(self._run(coverage, _ci("prove -l t")).status, Status.FAIL)

    def test_perltidy_and_tidyall(self) -> None:
        for line in ("perltidy --assert-tidy lib/Shop.pm", "perltidy -ast -q lib/Shop.pm", "tidyall --check-only -a"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)), Result.passed("CI enforces the perltidy style"))
        styled = {".perltidyrc": "--profile=pbp\n", **_ci("perltidy --assert-tidy lib/Shop.pm")}
        self.assertEqual(self._run(code_formatting, styled).message, ".perltidyrc is defined and CI runs perltidy")
        for line in ("perltidy -b lib/Shop.pm", "tidyall -a"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)

    def test_every_module_must_use_strict_and_warnings_and_perlcritic_must_run(self) -> None:
        passed = Result.passed(
            "strict Perl pragmas and lints are enabled: use strict and use warnings in every module, perlcritic"
        )
        self.assertEqual(self._run(compiler_warnings, _ci("perlcritic lib t")), passed)
        critic_test = {"t/perlcritic.t": "use Test::Perl::Critic;\nall_critic_ok();\n"}
        self.assertEqual(self._run(compiler_warnings, critic_test), passed)
        lax = {"lib/Shop/Cart.pm": "package Shop::Cart;\nuse strict;\n1;\n", **_ci("perlcritic lib")}
        result = self._run(compiler_warnings, lax)
        self.assertEqual(
            result,
            Result.warned(
                "missing Perl pragmas and lints: use strict and use warnings in every module", "found perlcritic"
            ),
        )
        # Installing Perl::Critic is not running it.
        self.assertEqual(self._run(compiler_warnings, _ci("cpanm Test::Perl::Critic")).status, Status.WARN)

    def test_warnings_are_fatal_in_the_modules_or_the_tests(self) -> None:
        fatal = {"lib/Shop.pm": "package Shop;\nuse strict;\nuse warnings FATAL => 'all';\n1;\n"}
        self.assertEqual(
            self._run(warnings_as_errors, fatal),
            Result.passed("warnings are treated as errors with use warnings FATAL => 'all'"),
        )
        tested = {"t/shop.t": "use Test::More;\nuse Test::Warnings;\nok(1);\ndone_testing;\n"}
        self.assertEqual(
            self._run(warnings_as_errors, tested),
            Result.passed("warnings are treated as errors with Test::Warnings in the tests"),
        )
        self.assertEqual(self._run(warnings_as_errors, TEST).status, Status.FAIL)

    def test_perlcritic_is_the_static_analyzer_and_cpan_audit_the_auditor(self) -> None:
        configured = {".perlcriticrc": "severity = 3\n", **_ci("perlcritic lib t")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("perlcritic (.perlcriticrc) runs"))
        self.assertEqual(self._run(static_analysis, _ci("tidyall -a")), Result.passed("perlcritic runs"))
        self.assertEqual(self._run(static_analysis, _ci("prove -l t")).status, Status.FAIL)
        self.assertEqual(
            self._run(dependency_audit, _ci("cpan-audit deps .")),
            Result.passed("CI audits the dependencies with cpan-audit"),
        )

    def test_the_outputs_of_each_build_system_must_be_ignored(self) -> None:
        distribution = "MakeMaker distribution"
        full = {".gitignore": "blib/\nMYMETA.*\ncover_db/\n"}
        self.assertEqual(run_in_layout(self, distribution, vcs_ignore, full).status, Status.PASS)
        result = run_in_layout(self, distribution, vcs_ignore, {".gitignore": "blib/\ncover_db/\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("MYMETA.*", " ".join((result.message, *result.details)))
        module_build = {
            "Build.PL": "",
            ".gitignore": "blib/\nMYMETA.*\ncover_db/\n_build/\n",
            "cpanfile": "",
            "local/": "",
        }
        module_build = {key: value for key, value in module_build.items() if not key.endswith("/")}
        result = run_in_layout(self, distribution, vcs_ignore, module_build)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("local/", " ".join((result.message, *result.details)))
        # Plain modules write no distribution outputs: only Devel::Cover's database.
        self.assertEqual(
            run_in_layout(self, "Perl modules", vcs_ignore, {".gitignore": "cover_db/\n"}).status, Status.PASS
        )
        self.assertEqual(run_in_layout(self, "Perl modules", vcs_ignore, {".gitignore": "blib/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_perl_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: PERL_MATRIX})
        self.assertIn("2 Perl version(s) (5.38, 5.40)", result.message)
        for line, version in (
            ("docker run perl:5.36 prove -l t", "5.36"),
            ("perlbrew install perl-5.38.2", "5.38.2"),
            ("prove -l t", "default"),
        ):
            with self.subTest(line=line):
                self.assertIn(f"1 Perl version(s) ({version})", self._run(platform_matrix, _ci(line)).message)
