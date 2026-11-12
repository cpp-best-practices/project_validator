from __future__ import annotations

import unittest
from typing import ClassVar

from project_validator.core import Check, Context, Result, Status
from project_validator.ecosystems import (
    BUILT_IN,
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    applies_to,
    ecosystems_for,
    formats,
    isolated_registry,
    languages_of,
    register,
    registered,
)
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.model import runs, subcommands, toolchain_patterns
from project_validator.ecosystems.perl import PERL_ECOSYSTEM
from project_validator.ecosystems.php import PHP
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.judging import by_ecosystem, check_each_ecosystem
from tests.support import FORMAT_ECOSYSTEM, evidence, make_context, temp_project, uses


class EcosystemsForTests(unittest.TestCase):
    def test_the_supported_ecosystems_of_the_languages(self) -> None:
        self.assertEqual(ecosystems_for(frozenset({"C++", "Python"}), BUILT_IN), (C_AND_CXX, PYTHON))
        self.assertEqual(ecosystems_for(frozenset({"Rust", "Python"}), (C_AND_CXX, RUST)), (RUST,))

    def test_no_ecosystem_for_unknown_languages(self) -> None:
        self.assertEqual(ecosystems_for(frozenset(), BUILT_IN), ())

    def test_no_ecosystem_when_none_of_the_supported_ones_is_used(self) -> None:
        self.assertEqual(ecosystems_for(C_FAMILY, (PYTHON, RUST)), ())


class CheckEachEcosystemTests(unittest.TestCase):
    RESULTS: ClassVar[dict[Ecosystem, Result]] = {
        C_AND_CXX: Result.warned("c warned", "c detail"),
        PYTHON: Result.passed("python passed", "python detail"),
        RUST: Result.failed("rust failed"),
        FORMAT_ECOSYSTEM: Result.passed("data passed"),
    }

    def _judge(self, files: dict[str, str]) -> Result:
        with temp_project(files) as root:
            return check_each_ecosystem(make_context(root), self.RESULTS, lambda result, _: result)

    def test_a_single_ecosystem_result_is_unchanged(self) -> None:
        self.assertEqual(self._judge({"Cargo.toml": ""}), self.RESULTS[RUST])
        self.assertEqual(self._judge({"main.c": ""}), self.RESULTS[C_AND_CXX])

    def test_a_project_of_no_recognised_ecosystem_is_skipped(self) -> None:
        self.assertEqual(
            self._judge({"README.md": ""}), Result(status=Status.SKIP, message="no recognised ecosystem in the project")
        )

    def test_several_ecosystems_combine_into_the_worst_result_with_labelled_findings(self) -> None:
        self.assertEqual(
            self._judge({"main.cpp": "", "setup.py": ""}),
            Result.warned("C/C++: c warned; Python: python passed", "C/C++: c detail", "Python: python detail"),
        )
        self.assertEqual(self._judge({"main.c": "", "Cargo.toml": "", "setup.py": ""}).status, Status.FAIL)

    def test_a_format_ecosystem_is_judged_as_a_language_one_is(self) -> None:
        with isolated_registry():
            register(FORMAT_ECOSYSTEM)
            self.assertEqual(self._judge({"a.wdata": ""}), self.RESULTS[FORMAT_ECOSYSTEM])
            both = self._judge({"a.wdata": "", "Cargo.toml": ""})
        self.assertEqual(both.message, "Rust: rust failed; Widget data: data passed")


ALPHA = BuildSystem(name="Alpha", files=("alpha.txt",))
BETA = BuildSystem(name="Beta", files=("beta.txt",))
WITH_DEFAULT = Ecosystem(label="X", languages=frozenset({"X"}), build_systems=(ALPHA, BETA), default_build_system=ALPHA)
WITHOUT_DEFAULT = Ecosystem(label="Y", languages=frozenset({"Y"}), build_systems=(ALPHA, BETA))


class BuildSystemTests(unittest.TestCase):
    def test_a_project_without_the_ecosystems_build_systems_uses_the_default(self) -> None:
        self.assertEqual(WITH_DEFAULT.used_build_systems(frozenset({"Cargo"})), (ALPHA,))
        self.assertEqual(WITH_DEFAULT.used_build_systems(frozenset({"Beta"})), (BETA,))
        self.assertEqual(WITHOUT_DEFAULT.used_build_systems(frozenset()), ())
        self.assertEqual(repr(WITH_DEFAULT), "Ecosystem(X)")


class CombinedTests(unittest.TestCase):
    SKIPPED = Result(status=Status.SKIP, message="not applicable")

    def test_skipped_ecosystems_are_left_out(self) -> None:
        self.assertEqual(by_ecosystem({C_AND_CXX: self.SKIPPED, PYTHON: Result.failed("no")}), Result.failed("no"))

    def test_a_skip_only_when_every_ecosystem_is_skipped(self) -> None:
        result = by_ecosystem({C_AND_CXX: self.SKIPPED, PYTHON: self.SKIPPED})
        self.assertEqual(result.status, Status.SKIP)
        # The same result for every ecosystem is said once.
        self.assertEqual(result.message, "not applicable")


class RegistryTests(unittest.TestCase):
    def test_registering_the_same_ecosystem_again_does_nothing(self) -> None:
        with isolated_registry():
            register(WITH_DEFAULT)
            register(WITH_DEFAULT)
            self.assertEqual(registered(), (*BUILT_IN, WITH_DEFAULT))

    def test_a_check_limited_by_languages_applies_to_the_ecosystems_of_those_languages(self) -> None:
        def run(_: Context) -> Result:
            return Result.passed("")

        self.assertEqual(
            applies_to(Check(name="c", description="", run=run, languages_from=lambda: frozenset({"C"}))), ("C/C++",)
        )
        self.assertEqual(applies_to(Check(name="any", description="", run=run)), ())


class ToolchainUsageTests(unittest.TestCase):
    """A job uses a toolchain when one of the commands it runs is one of the toolchain's programs: a program by
    name, with the subcommands after it. Text is matched only for what is not a command: a setup action, an action
    of the ecosystem's, a version."""

    def test_a_program_is_matched_by_name_wherever_it_is_run_from(self) -> None:
        lines = ("cargo test", "/usr/local/bin/cargo build", "cargo.exe build", "CARGO_TERM_COLOR=always cargo test")
        for line in lines:
            with self.subTest(line=line):
                self.assertTrue(uses(RUST, line))

    def test_a_subcommand_of_another_program_is_that_programs(self) -> None:
        self.assertTrue(uses(PERL_ECOSYSTEM, "cover -test"))
        self.assertTrue(uses(PERL_ECOSYSTEM, "prove -l t && cover -report codecov"))
        for line in ("raco cover -f codecov .", "go tool cover -html=c.out", "npx cover"):
            with self.subTest(line=line):
                self.assertFalse(uses(PERL_ECOSYSTEM, line))

    def test_a_word_in_text_is_not_a_program(self) -> None:
        for line in ("echo cargo", "languages: python, rust", "name: cargo-audit", "# cargo build is slow"):
            with self.subTest(line=line):
                self.assertFalse(uses(RUST, line))
                self.assertFalse(uses(PYTHON, line))

    def test_a_program_run_from_the_toolchains_directory_uses_it(self) -> None:
        for line in ("vendor/bin/phpunit", "./vendor/bin/pest --coverage", "php -d memory_limit=-1 vendor/bin/psalm"):
            with self.subTest(line=line):
                self.assertTrue(uses(PHP, line))
        self.assertFalse(uses(PHP, "node_modules/.bin/jest"))

    def test_an_action_is_matched_after_its_owner(self) -> None:
        patterns = toolchain_patterns("Widget", actions=("widget-actions/",), setup=("widget",))
        for line in ("uses: acme/widget-actions/setup@v1", "uses: acme/setup-widget@v2"):
            with self.subTest(line=line):
                self.assertTrue(patterns.used_by(*evidence(line)))
        self.assertFalse(patterns.used_by(*evidence("uses: acme/my-widget-actions/setup@v1")))
        self.assertIsNone(toolchain_patterns("Widget", programs=("widget",)).usage)

    def test_runs_and_subcommands(self) -> None:
        self.assertEqual(subcommands("go", "build", "test"), (("go", "build"), ("go", "test")))
        self.assertTrue(runs((("go", "test", "./..."),), subcommands("go", "build", "test")))
        self.assertFalse(runs((("go", "tool", "cover"),), subcommands("go", "build", "test")))
        self.assertTrue(runs(((r"vendor\bin\phpunit",),), (), directories=("vendor/bin",)))
        self.assertFalse(runs(((),), (("go",),), directories=("vendor/bin",)))


class FormatTests(unittest.TestCase):
    """A format is a kind of file that is not a program: an ecosystem of `kind` format, whose `languages` are its
    format names. It has no toolchain (nothing has a version to pin); it may have build systems (a documentation
    site is built) and its files are judged for hygiene only."""

    def test_a_format_has_no_toolchain(self) -> None:
        with self.assertRaises(ValueError) as raised:
            Ecosystem(
                label="Widget data",
                kind="format",
                languages=frozenset({"WDATA"}),
                toolchain=toolchain_patterns("WDATA", programs=("wdata",)),
            )
        self.assertEqual(str(raised.exception), "Widget data: a format has no toolchain")

    def test_the_formats_are_the_names_of_the_format_ecosystems(self) -> None:
        with isolated_registry():
            register(FORMAT_ECOSYSTEM)
            self.assertIn("WDATA", formats())
            languages = languages_of(found for found in registered() if found.kind == "language")
            self.assertFalse(formats() & languages)
        self.assertNotIn("WDATA", formats())

    def test_a_check_of_a_format_applies_to_the_formats_ecosystem(self) -> None:
        def run(_: Context) -> Result:
            return Result.passed("")

        selected = Check(name="w", description="", run=run, languages_from=lambda: frozenset({"WDATA"}))
        with isolated_registry():
            register(FORMAT_ECOSYSTEM)
            self.assertEqual(applies_to(selected), ("Widget data",))
