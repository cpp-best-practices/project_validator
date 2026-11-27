"""What a project turns off in its tools (upstream #295): the diagnostics their configuration disables, with their kind,
scope and whether a comment says why, and the suppressions written in the code, counted per file and tool."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.facts import Facts
from project_validator.facts.suppressions import BLANKET, FILE, GLOBAL, KEY, STYLISTIC, Disabled, Suppressions
from tests.support import github_job, make_context, temp_project


def _facts(files: Mapping[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _disabled(files: Mapping[str, str]) -> list[tuple[str, str, str, str, bool]]:
    found = _facts(files).of(Disabled)
    return [(fact.tool, fact.diagnostic, fact.kind, fact.scope, fact.justified) for fact in found]


def _suppressions(files: Mapping[str, str]) -> dict[tuple[str, str], tuple[int, int, bool]]:
    found = _facts(files).of(Suppressions)
    return {(fact.origin.path, fact.tool): (fact.count, fact.justified, fact.blanket) for fact in found}


class DisabledTests(unittest.TestCase):
    def test_clang_tidy_checks_turned_off(self) -> None:
        files = {
            "main.cpp": "int main() {}\n",
            ".clang-tidy": "Checks: '-*,bugprone-*,-bugprone-easily-swappable-parameters,-readability-magic-numbers'\n",
        }
        self.assertEqual(
            _disabled(files),
            [
                ("clang-tidy", "bugprone-easily-swappable-parameters", KEY, GLOBAL, False),
                ("clang-tidy", "readability-magic-numbers", STYLISTIC, GLOBAL, False),
            ],
        )
        everything = {**files, ".clang-tidy": "Checks: 'bugprone-*,-*'\n"}
        self.assertEqual(_disabled(everything), [("clang-tidy", "*", BLANKET, GLOBAL, False)])

    def test_ruff_ignores_globally_and_per_file_and_a_comment_justifies_one(self) -> None:
        pyproject = (
            "[project]\nname = 'app'\n[tool.ruff.lint]\n"
            'ignore = [\n  "E501",  # long URLs in docstrings\n  "B008",\n]\n'
            '[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["S101"]\n'
        )
        found = _disabled({"pyproject.toml": pyproject, "app.py": ""})
        self.assertEqual(
            found,
            [
                ("ruff check", "E501", STYLISTIC, GLOBAL, True),
                ("ruff check", "B008", KEY, GLOBAL, False),
                ("ruff check", "S101", KEY, FILE, False),
            ],
        )
        self.assertIn(("ruff check", "ALL", BLANKET, GLOBAL, False), _disabled({"ruff.toml": 'ignore = ["ALL"]\n'}))

    def test_flake8_pylint_and_mypy(self) -> None:
        files = {
            "app.py": "",
            ".flake8": "[flake8]\nextend-ignore = E203, W503\nper-file-ignores =\n    tests/*: S101\n",
            "mypy.ini": "[mypy]\ndisable_error_code = import-untyped\nignore_errors = True\n",
            ".pylintrc": "[MESSAGES CONTROL]\ndisable = all\n",
        }
        found = _disabled(files)
        for expected in (
            ("flake8", "E203", STYLISTIC, GLOBAL, False),
            ("flake8", "S101", KEY, FILE, False),
            ("mypy", "import-untyped", KEY, GLOBAL, False),
            ("mypy", "ignore_errors", BLANKET, GLOBAL, False),
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, found)

    def test_typescripts_strict_flags_turned_off(self) -> None:
        files = {
            "package.json": '{"name": "a", "main": "index.ts"}',
            "index.ts": "",
            "tsconfig.json": '{"compilerOptions": {"strict": true, "strictNullChecks": false, "noImplicitAny": true}}',
        }
        self.assertEqual(_disabled(files), [("tsc", "strictNullChecks", KEY, GLOBAL, False)])

    def test_clippy_lints_allowed(self) -> None:
        files = {
            "Cargo.toml": '[package]\nname = "a"\n[lints.clippy]\nunwrap_used = "allow"\nmodule_name_repetitions = '
            '{ level = "allow", priority = 1 }\npedantic = "warn"\n',
            "src/lib.rs": "",
        }
        found = _disabled(files)
        self.assertIn(("clippy", "unwrap_used", KEY, GLOBAL, False), found)
        self.assertIn(("clippy", "module_name_repetitions", STYLISTIC, GLOBAL, False), found)
        self.assertNotIn("pedantic", [fact[1] for fact in found])

    def test_only_the_codes_of_bug_finding_plugins_are_key(self) -> None:
        """Bandit's S101, not flake8-simplify's SIM102; pyflakes' F401, not flynt's FLY002; bugbear's B008, not
        flake8-blind-except's BLE001."""
        ruff = {"ruff.toml": 'ignore = ["S101", "SIM102", "F401", "FLY002", "B008", "BLE001", "B"]\n', "app.py": ""}
        kinds = {diagnostic: kind for _, diagnostic, kind, _, _ in _disabled(ruff)}
        self.assertEqual(
            kinds,
            {
                "S101": KEY,
                "SIM102": STYLISTIC,
                "F401": KEY,
                "FLY002": STYLISTIC,
                "B008": KEY,
                "BLE001": STYLISTIC,
                "B": KEY,
            },
        )

    def test_only_clippys_correctness_lints_are_key(self) -> None:
        files = {
            "Cargo.toml": '[package]\nname = "a"\n[lints.clippy]\nmap_unwrap_or = "allow"\n'
            'missing_panics_doc = "allow"\ncast_possible_truncation = "allow"\ncorrectness = "allow"\n'
            'unwrap_used = "allow"\n',
            "src/lib.rs": "",
        }
        kinds = {diagnostic: kind for _, diagnostic, kind, _, _ in _disabled(files)}
        self.assertEqual(
            kinds,
            {
                "map_unwrap_or": STYLISTIC,
                "missing_panics_doc": STYLISTIC,
                "cast_possible_truncation": STYLISTIC,
                "correctness": KEY,
                "unwrap_used": KEY,
            },
        )

    def test_a_w_is_a_compilers_only_on_a_compilers_command_line(self) -> None:
        files = {"main.go": "", **github_job("ubuntu-latest", 'go build -ldflags "-s -w" .', "grep -w main main.go")}
        self.assertEqual(_disabled(files), [])

    def test_compiler_warnings_turned_off_on_a_command_line(self) -> None:
        files = {
            "main.c": "",
            **github_job("ubuntu-latest", "gcc -Wall -Wno-conversion -Wno-unused-parameter -w main.c"),
        }
        self.assertEqual(
            _disabled(files),
            [
                ("compiler", "-Wno-conversion", KEY, GLOBAL, False),
                ("compiler", "-Wno-unused-parameter", STYLISTIC, GLOBAL, False),
                ("compiler", "-w", BLANKET, GLOBAL, False),
            ],
        )


class SuppressionTests(unittest.TestCase):
    def test_inline_suppressions_are_counted_per_file_and_tool_with_those_that_say_why(self) -> None:
        files = {
            "app.py": (
                "import os  # noqa: F401\n"
                "x = 1  # noqa: E501 - a long URL\n"
                "y = f()  # type: ignore[no-untyped-call]\n"
                "z = 2  # pylint: disable=invalid-name\n"
            ),
            "lib.cpp": "int f(); // NOLINT(bugprone-x): the API takes ownership\nint g(); // NOLINT\n",
            "src/lib.rs": "#![allow(warnings)]\n#[allow(clippy::unwrap_used)] // checked above\nfn f() {}\n",
            "index.ts": "// @ts-ignore\nconst a = 1; // eslint-disable-line no-console -- logging is the point\n",
            "package.json": '{"name": "a", "main": "index.ts"}',
            "Cargo.toml": '[package]\nname = "a"\n',
        }
        found = _suppressions(files)
        self.assertEqual(found[("app.py", "ruff check")], (2, 1, False))
        self.assertEqual(found[("app.py", "flake8")], (2, 1, False))
        self.assertEqual(found[("app.py", "mypy")], (1, 0, False))
        self.assertEqual(found[("app.py", "pylint")], (1, 0, False))
        self.assertEqual(found[("lib.cpp", "clang-tidy")], (2, 1, False))
        self.assertEqual(found[("src/lib.rs", "clippy")], (2, 1, True))
        self.assertEqual(found[("index.ts", "tsc")], (1, 0, False))
        self.assertEqual(found[("index.ts", "eslint")], (1, 1, False))

    def test_only_the_products_code_counts(self) -> None:
        self.assertEqual(_suppressions({"app.py": "", "tests/test_app.py": "import os  # noqa: F401\n"}), {})

    def test_a_file_turned_off_whole(self) -> None:
        found = _suppressions({"app.py": "# mypy: ignore-errors\nx = 1\n", "index.ts": "/* eslint-disable */\n"})
        self.assertEqual(found[("app.py", "mypy")], (0, 0, True))


if __name__ == "__main__":
    unittest.main()
