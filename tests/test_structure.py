import unittest

from project_validator.core import Check, Result, Status
from project_validator.runner import run_check
from project_validator.structure import C_FAMILY
from tests.support import FIXTURES, make_context, temp_project

GITHUB_CI = """\
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: cargo test
"""


def _check(name: str, languages: frozenset[str] = frozenset()) -> Check:
    return Check(name=name, description=name, run=lambda context: Result.passed("ran"), languages=languages)


class ProjectStructureTests(unittest.TestCase):
    def test_cmake_project_is_c_family(self) -> None:
        structure = make_context(FIXTURES / "well_configured").structure
        self.assertEqual(structure.languages, C_FAMILY)
        self.assertEqual(structure.build_systems, frozenset({"CMake"}))
        self.assertEqual(structure.ci_providers, ("GitHub Actions",))
        self.assertTrue(structure.ci_jobs)

    def test_build_files_name_their_languages(self) -> None:
        cases = {
            "Cargo.toml": ({"Rust"}, {"Cargo"}),
            "pyproject.toml": ({"Python"}, {"Python packaging"}),
            "setup.py": ({"Python"}, {"Python packaging"}),
            "meson.build": (set(C_FAMILY), {"Meson"}),
        }
        for build_file, (languages, build_systems) in cases.items():
            with self.subTest(build_file), temp_project({build_file: ""}) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, languages)
                self.assertEqual(structure.build_systems, build_systems)

    def test_source_files_name_their_languages(self) -> None:
        files = {"src/main.rs": "", "tools/gen.py": "", "lib/a.c": "", "lib/b.hpp": "", "lib/ambiguous.h": ""}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.languages, {"Rust", "Python", "C", "C++"})

    def test_hidden_and_vendored_directories_are_not_mapped(self) -> None:
        files = {"Cargo.toml": "", ".venv/x.py": "", "node_modules/y.cpp": "", "target/CMakeCache.txt": ""}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.languages, {"Rust"})

    def test_map_is_serialisable(self) -> None:
        mapped = make_context(FIXTURES / "well_configured").structure.as_dict()
        self.assertEqual(mapped["languages"], ["C", "C++"])
        self.assertEqual(mapped["build_systems"], ["CMake"])
        self.assertEqual(mapped["ci"]["files"], [".github/workflows/ci.yml", ".github/workflows/codeql-analysis.yml"])
        job = mapped["ci"]["jobs"][0]
        self.assertEqual(set(job), {"name", "os", "compilers", "configurations"})


class LanguageApplicabilityTests(unittest.TestCase):
    def test_c_family_checks_are_skipped_for_a_rust_project(self) -> None:
        with temp_project({"Cargo.toml": "", ".github/workflows/ci.yml": GITHUB_CI}) as root:
            result = run_check(_check("warnings", C_FAMILY), make_context(root))
        self.assertEqual(result.status, Status.SKIP)
        self.assertIn("Rust", result.message)

    def test_language_agnostic_checks_always_run(self) -> None:
        with temp_project({"Cargo.toml": ""}) as root:
            self.assertEqual(run_check(_check("generic"), make_context(root)).status, Status.PASS)

    def test_matching_checks_run(self) -> None:
        context = make_context(FIXTURES / "well_configured")
        self.assertEqual(run_check(_check("cpp", frozenset({"C++"})), context).status, Status.PASS)

    def test_every_check_runs_when_no_language_is_recognised(self) -> None:
        with temp_project({"README.md": ""}) as root:
            self.assertEqual(run_check(_check("cpp", C_FAMILY), make_context(root)).status, Status.PASS)

    def test_builtin_compiler_checks_declare_c_family(self) -> None:
        from project_validator.plugins import discover

        languages = {found.name: found.languages for found in discover().checks}
        compiler_checks = (
            "ci-build-types", "compiler-warnings", "coverage", "ctest-runs", "cxx-extensions", "platform-matrix"
        )
        for name in compiler_checks:
            self.assertEqual(languages[name], C_FAMILY, name)
        for name in ("ci-present", "security-scanning"):
            self.assertEqual(languages[name], frozenset(), name)
