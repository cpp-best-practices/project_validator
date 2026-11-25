"""Bazel as a build system (upstream #207): recognised by its MODULE.bazel, WORKSPACE and BUILD.bazel files; its
`--compilation_mode` is the build type, and `bazel test` runs the tests its BUILD files define."""

from __future__ import annotations

import unittest

from project_validator.build_systems.bazel.build import BAZEL
from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.tests_run import tests_run
from project_validator.core import Result, Status
from project_validator.facts import Setting, Unknown
from project_validator.questions.testing import tests
from tests.support import command, github_job, make_context, temp_project

# googletest's and Catch2's: a module, a BUILD file with a library and its test.
CXX = {
    "MODULE.bazel": 'module(name = "app")\nbazel_dep(name = "googletest", version = "1.15.2")\n',
    "BUILD.bazel": (
        'load("@rules_cc//cc:defs.bzl", "cc_library", "cc_test")\n'
        'cc_library(name = "app", srcs = ["src/app.cc"], hdrs = ["include/app.h"])\n'
        'cc_test(name = "app_test", srcs = ["test/app_test.cc"], deps = [":app", "@googletest//:gtest_main"])\n'
    ),
    "src/app.cc": "int f() { return 1; }\n",
    "include/app.h": "int f();\n",
    "test/app_test.cc": "#include <gtest/gtest.h>\n",
}
BAZEL_TESTS = "tests defined by Bazel test rules (cc_test, swift_test, sh_test, …) in BUILD files"


class RecognitionTests(unittest.TestCase):
    def test_a_module_workspace_or_build_file_makes_a_bazel_project(self) -> None:
        for build_file in ("MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel", "BUILD.bazel"):
            with self.subTest(build_file=build_file), temp_project({build_file: "", "src/a.cc": ""}) as root:
                self.assertIn("Bazel", make_context(root).structure.build_systems)

    def test_the_rules_and_tests_of_each_build_file_are_read(self) -> None:
        tools = 'sh_test(name = "lint", srcs = ["lint.sh"])\nexports_files(["lint.sh"])\nsh_test(srcs = ["x.sh"])\n'
        files = {**CXX, "tools/BUILD": tools}
        with temp_project(files) as root:
            settings = {
                (found.path, found.key): found.value for found in make_context(root).facts.where(Setting, tool="Bazel")
            }
        self.assertEqual(
            settings,
            {
                ("BUILD.bazel", "rules"): ("cc_library", "cc_test"),
                ("BUILD.bazel", "test.app_test"): ("cc_test", "test/app_test.cc"),
                ("tools/BUILD", "rules"): ("exports_files", "sh_test"),
                ("tools/BUILD", "test.lint"): ("sh_test", "tools/lint.sh"),
            },
        )

    def test_a_build_file_that_parses_in_part_is_read_for_that_part(self) -> None:
        for text, expected in (
            ('cc_test(name = "a",, )\nsh_test(name = "b")\n', {"rules": ("sh_test",), "test.b": ("sh_test",)}),
            ('cc_test(name = "a",, )\n', {}),
        ):
            with self.subTest(text=text), temp_project({"MODULE.bazel": "", "BUILD.bazel": text}) as root:
                facts = make_context(root).facts
                self.assertEqual({found.key: found.value for found in facts.where(Setting, tool="Bazel")}, expected)
                self.assertEqual(bool(facts.of(Unknown)), not expected)

    def test_bazel_output_directories_are_build_trees(self) -> None:
        files = {**CXX, "bazel-bin/src/app.cc": "", "bazel-app/BUILD.bazel": 'cc_test(name = "copy")\n'}
        with temp_project(files) as root:
            facts = make_context(root).facts
        self.assertEqual({found.path for found in facts.where(Setting, tool="Bazel")}, {"BUILD.bazel"})


class BuildTypeTests(unittest.TestCase):
    def test_the_compilation_mode_is_the_build_type(self) -> None:
        for line, expected in (
            ("bazel build -c opt //...", {"release"}),
            ("bazelisk test --compilation_mode=dbg //...", {"debug"}),
            ("bazel --batch build --compilation_mode opt //:all", {"release"}),
            ("bazel build //...", set()),  # fastbuild, neither Debug nor Release
            ("bazel build -c fastbuild //...", set()),
            ("bazel build -c dbg -c opt //...", {"release"}),  # the last wins
            ("bazel query -c opt //...", set()),  # builds nothing
            ("cmake -c opt", set()),
        ):
            with self.subTest(line=line):
                self.assertEqual(BAZEL.build_types(command(line)), expected)  # type: ignore[misc]

    def test_ci_builds_debug_and_release_with_bazel(self) -> None:
        matrix = "    strategy:\n      matrix:\n        mode: [dbg, opt]\n"
        workflow = (
            "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
            + matrix
            + "    steps:\n      - run: bazelisk build --compilation_mode=${{ matrix.mode }} //...\n"
        )
        with temp_project({**CXX, ".github/workflows/ci.yml": workflow}) as root:
            result = ci_build_types.run(make_context(root))
        # Debug and Release are both built; only their builds with sanitizers are missing.
        self.assertEqual(result.details, ("linux / gcc: missing Debug + sanitizers, Release + sanitizers",))


class TestRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        with temp_project(files) as root:
            return tests_run.run(make_context(root))

    def test_bazel_test_runs_the_tests_its_build_files_define(self) -> None:
        for line in ("bazel test //...", "bazelisk --batch test --config=ci //test/...", "bazel coverage //..."):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run({**CXX, **github_job("ubuntu-latest", line)}),
                    Result.passed(f"{BAZEL_TESTS}: 1 file(s), run by bazel test"),
                )

    def test_building_runs_no_test(self) -> None:
        result = self._run({**CXX, **github_job("ubuntu-latest", "bazel build //...")})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no CI configuration runs", result.message)


class TestLanguageTests(unittest.TestCase):
    """Each test rule counts for the language it tests: that of the sources it lists, or else its kind's."""

    @staticmethod
    def _root(files: dict[str, str], language: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """The BUILD files said to define the root unit's tests of `language`, and the unknowns that may hide one."""
        with temp_project({"MODULE.bazel": "", **files}) as root:
            [unit] = (found for found in tests(language, make_context(root).facts).units if found.unit == ".")
        return unit.definitions(), unit.unknown_definitions

    def test_a_swift_test_is_no_test_of_c(self) -> None:
        # SwiftLint's: C sources, and swift_test rules.
        files = {"src/a.c": "", "Sources/A.swift": "", "Tests/T.swift": "", "BUILD": 'swift_test(name = "t")\n'}
        self.assertEqual(self._root(files, "Swift"), (("BUILD",), ()))
        self.assertEqual(self._root(files, "C"), ((), ()))

    def test_a_cc_test_tests_c_and_cxx_unless_its_sources_say_which(self) -> None:
        sources = {"a.c": "", "b.cc": "", "x.asd": "", "Sources/A.swift": ""}
        for rule, expected in (
            ('cc_test(name = "t", srcs = glob(["*_test.cc"]))', {"C": ("BUILD",), "C++": ("BUILD",), "Swift": ()}),
            ('cc_test(name = "t", srcs = ["b.cc", ":gen"])', {"C": (), "C++": ("BUILD",), "Swift": ()}),
            ('cc_test(name = "t", srcs = ["a.c"])', {"C": ("BUILD",), "C++": (), "Swift": ()}),
            ('cc_test(name = "t", srcs = ["x.asd"])', {"C": ("BUILD",), "C++": ("BUILD",), "Swift": ()}),  # no language
        ):
            for language, defined in expected.items():
                with self.subTest(rule=rule, language=language):
                    self.assertEqual(self._root({**sources, "BUILD": rule + "\n"}, language), (defined, ()))

    def test_a_custom_test_rule_tests_the_language_of_its_sources(self) -> None:
        # envoy's api_cc_test and api_go_test macros.
        rules = 'api_cc_test(name = "a", srcs = ["a_test.cc"])\napi_go_test(name = "g", srcs = ["g_test.go"])\n'
        files = {"build/BUILD": rules, "build/a_test.cc": "", "build/g_test.go": "", "lib.c": ""}
        self.assertEqual(self._root(files, "C++"), (("build/BUILD",), ()))
        self.assertEqual(self._root(files, "C"), ((), ()))
        with temp_project({"MODULE.bazel": "", **files}) as root:
            self.assertEqual(make_context(root).facts.of(Unknown), ())

    def test_labels_say_no_language(self) -> None:
        for label in (":gen", "//lib:gen", "@other//:gen"):
            with self.subTest(label=label):
                rule = f'api_cc_test(name = "a", srcs = ["{label}"])\n'
                defined, unknown = self._root({"a.cc": "", "BUILD": rule}, "C++")
                self.assertEqual((defined, len(unknown)), ((), 1))

    def test_a_custom_test_rule_whose_sources_are_unwritten_is_unknown(self) -> None:
        # protovalidate's buf_lint_test, which lists no sources.
        files = {"a.cc": "", "BUILD": 'buf_lint_test(name = "lint", targets = [":protos"])\n'}
        defined, unknown = self._root(files, "C++")
        self.assertEqual(defined, ())
        self.assertEqual(len(unknown), 1)
        self.assertIn("the Bazel test rule lint: its kind, buf_lint_test, and its sources do not say", unknown[0])

    def test_a_known_test_rule_of_another_language_is_not_unknown(self) -> None:
        files = {"a.cc": "", "BUILD": 'py_test(name = "p", srcs = glob(["*.py"]))\nsh_test(name = "s")\n'}
        self.assertEqual(self._root(files, "C++"), ((), ()))
