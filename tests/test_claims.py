"""How a tool claims the commands that run it: by its program and subcommands, by its options, and by combinations."""

from __future__ import annotations

import unittest

from project_validator.facts import Facts
from project_validator.facts.arguments import starts_with
from project_validator.facts.testing import tested
from project_validator.facts.tools import all_of, any_of, starts, when, with_option
from tests.support import command


class StartsWithTests(unittest.TestCase):
    def test_the_program_is_matched_by_name(self) -> None:
        self.assertEqual(starts_with(("./vendor/bin/phpunit", "--coverage"), ("phpunit",)), ("phpunit",))
        self.assertEqual(
            starts_with(("C:\\tools\\cmake.exe", "--build", "b"), ("cmake", "--build")), ("cmake", "--build")
        )

    def test_a_scoped_npm_package_is_one_name(self) -> None:
        # `npx @redocly/cli lint` runs the package, not a program `cli` in a directory `@redocly`.
        self.assertEqual(starts_with(("@redocly/cli", "lint"), ("@redocly/cli", "lint")), ("@redocly/cli", "lint"))
        self.assertEqual(starts_with(("@redocly/cli", "lint"), ("cli", "lint")), ("cli", "lint"))
        # Its own name still counts, as it did when the scope read as a directory.
        self.assertEqual(starts_with(("@biomejs/biome", "ci"), ("biome", "ci")), ("biome", "ci"))
        self.assertEqual(starts_with(("@scope/bin/tool",), ("tool",)), ("tool",))

    def test_the_first_matching_prefix_is_returned(self) -> None:
        self.assertEqual(
            starts_with(("cargo", "test", "--all"), ("cargo", "fmt"), ("cargo", "test")), ("cargo", "test")
        )

    def test_subcommands_must_follow_the_program(self) -> None:
        self.assertIsNone(starts_with(("go", "-C", "x", "test"), ("go", "test")))
        self.assertIsNone(starts_with(("go",), ("go", "test")))
        self.assertIsNone(starts_with((), ("go",)))


class ClaimTests(unittest.TestCase):
    def test_starts_reads_the_command_as_run(self) -> None:
        runs = starts(("go", "test"), ("gotestsum",))
        self.assertTrue(runs(command("go test ./...")))
        self.assertTrue(runs(command("$GO test", env={"GO": "go"})))
        self.assertFalse(runs(command("go build ./...")))

    def test_with_option_accepts_the_option_alone_or_with_a_value(self) -> None:
        asked = with_option("--coverage", "-c")
        self.assertTrue(asked(command("bun test --coverage")))
        self.assertTrue(asked(command("bun test --coverage=lcov")))
        self.assertTrue(asked(command("bun test -c")))
        self.assertFalse(asked(command("bun test")))

    def test_all_of_and_any_of_combine_conditions(self) -> None:
        covered = all_of(starts(("swift", "test")), with_option("--enable-code-coverage"))
        self.assertTrue(covered(command("swift test --enable-code-coverage")))
        self.assertFalse(covered(command("swift test")))
        self.assertFalse(covered(command("swift build --enable-code-coverage")))
        tests = any_of(starts(("swift", "test")), all_of(starts(("xcodebuild",)), with_option("test")))
        self.assertTrue(tests(command("swift test")))
        self.assertTrue(tests(command("xcodebuild test -scheme App")))
        self.assertFalse(tests(command("xcodebuild build")))

    def test_when_makes_a_claim_of_a_condition(self) -> None:
        claim = when(all_of(starts(("go", "test")), with_option("-cover")), tested)
        self.assertIsNotNone(claim(command("go test -cover ./..."), Facts()))
        self.assertIsNone(claim(command("go test ./..."), Facts()))
