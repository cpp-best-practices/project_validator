import unittest
from unittest import mock

from project_validator.core import Check, Result, Status
from project_validator.plugins import discover
from project_validator.runner import run_check
from project_validator.structure import C_FAMILY
from tests.support import (
    C_FAMILY_LAYOUTS,
    CI_FILES,
    FIXTURES,
    OTHER_LANGUAGE_LAYOUTS,
    PROJECT_LAYOUTS,
    layout_project,
    make_context,
    temp_project,
)

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

    def test_every_layout_is_mapped_with_every_ci_provider(self) -> None:
        for layout in PROJECT_LAYOUTS:
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: "jobs: {}\n"}, ci=provider) as root:
                    structure = make_context(root).structure
                    self.assertEqual(structure.languages, layout.languages)
                    self.assertEqual(structure.build_systems, layout.build_systems)
                    self.assertEqual(structure.ci_providers, (provider,))
                    self.assertEqual(structure.ci_files, (path,))

    def test_every_layout_is_mapped_without_ci(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, layout.languages)
                self.assertEqual((structure.ci_providers, structure.ci_files, structure.ci_jobs), ((), (), ()))

    def test_build_files_name_their_languages(self) -> None:
        cases = {
            "Cargo.toml": ({"Rust"}, {"Cargo"}),
            "pyproject.toml": ({"Python"}, {"Python packaging"}),
            "setup.py": ({"Python"}, {"Python packaging"}),
            "meson.build": (set(), {"Meson"}),
        }
        for build_file, (languages, build_systems) in cases.items():
            with self.subTest(build_file), temp_project({build_file: ""}) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, languages)
                self.assertEqual(structure.build_systems, build_systems)

    def test_meson_languages_come_from_the_project_declaration(self) -> None:
        cases = {
            "project('demo', 'rust')": {"Rust"},
            "project('demo', ['c', 'cpp'], version: '1.0')": set(C_FAMILY),
            "project(\n  'demo', # 'c'\n  'cpp',\n  default_options: ['cpp_std=c++20'],\n)": {"C++"},
            "project('demo', version: run_command('cat', 'VERSION').stdout())": set(),
            "project()": set(),
        }
        for declaration, languages in cases.items():
            with self.subTest(declaration), temp_project({"meson.build": declaration, "sub/meson.build": ""}) as root:
                self.assertEqual(make_context(root).structure.languages, languages)

    def test_source_files_name_their_languages(self) -> None:
        files = {"src/main.rs": "", "tools/gen.py": "", "lib/a.c": "", "lib/b.hpp": "", "lib/ambiguous.h": ""}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.languages, {"Rust", "Python", "C", "C++"})

    def test_hidden_and_vendored_directories_are_not_mapped(self) -> None:
        files = {"Cargo.toml": "", ".venv/x.py": "", "node_modules/y.cpp": "", "target/CMakeCache.txt": ""}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.languages, {"Rust"})

    def test_cargo_build_output_is_not_mapped(self) -> None:
        generated = "debug/build/native-sys/out/generated.c"
        layouts = {
            "default target": {"Cargo.toml": "", "src/main.rs": "", f"target/{generated}": ""},
            "tagged target": {"Cargo.toml": "", "build-out/CACHEDIR.TAG": "", f"build-out/{generated}": ""},
        }
        for layout, files in layouts.items():
            with self.subTest(layout), temp_project(files) as root:
                self.assertEqual(make_context(root).structure.languages, {"Rust"})

    def test_every_layout_map_is_serialisable(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                mapped = make_context(root).structure.as_dict()
                self.assertEqual(mapped["languages"], sorted(layout.languages))
                self.assertEqual(mapped["build_systems"], sorted(layout.build_systems))
                self.assertEqual(mapped["ci"], {"providers": [], "files": [], "jobs": []})

    def test_map_is_serialisable(self) -> None:
        mapped = make_context(FIXTURES / "well_configured").structure.as_dict()
        self.assertEqual(mapped["languages"], ["C", "C++"])
        self.assertEqual(mapped["build_systems"], ["CMake"])
        self.assertEqual(mapped["ci"]["files"], [".github/workflows/ci.yml", ".github/workflows/codeql-analysis.yml"])
        job = mapped["ci"]["jobs"][0]
        self.assertEqual(set(job), {"name", "os", "compilers", "configurations"})


class LanguageApplicabilityTests(unittest.TestCase):
    def test_c_family_checks_are_skipped_for_other_languages(self) -> None:
        for layout in OTHER_LANGUAGE_LAYOUTS:
            with layout_project(self, layout, {".github/workflows/ci.yml": GITHUB_CI}) as root:
                result = run_check(_check("warnings", C_FAMILY), make_context(root))
                self.assertEqual(result.status, Status.SKIP)
                self.assertEqual(
                    result.message, f"not applicable to {', '.join(sorted(layout.languages))} (applies to C, C++)"
                )

    def test_c_family_checks_run_for_c_family_and_unrecognised_languages(self) -> None:
        for layout in C_FAMILY_LAYOUTS:
            with layout_project(self, layout) as root:
                self.assertEqual(run_check(_check("warnings", C_FAMILY), make_context(root)).status, Status.PASS)

    def test_language_agnostic_checks_always_run(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                self.assertEqual(run_check(_check("generic"), make_context(root)).status, Status.PASS)

    def test_language_agnostic_checks_run_when_the_project_cannot_be_mapped(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root, mock.patch(
                "project_validator.structure.map_project", side_effect=RuntimeError("unparseable CI")
            ):
                context = make_context(root)
                self.assertEqual(run_check(_check("generic"), context).status, Status.PASS)
                self.assertEqual(run_check(_check("cpp", C_FAMILY), context).status, Status.ERROR)

    def test_checks_run_exactly_for_the_layouts_in_their_languages(self) -> None:
        for language in ("C", "C++", "Rust", "Python"):
            selected = _check(language, frozenset({language}))
            for layout in PROJECT_LAYOUTS:
                with layout_project(self, layout, language=language) as root:
                    applies = not layout.languages or language in layout.languages
                    expected = Status.PASS if applies else Status.SKIP
                    self.assertEqual(run_check(selected, make_context(root)).status, expected)

    def test_builtin_checks_are_skipped_only_outside_their_languages(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, {".github/workflows/ci.yml": GITHUB_CI}) as root:
                context = make_context(root)
                for found in discover().checks:
                    skipped = run_check(found, context).status == Status.SKIP
                    self.assertEqual(skipped, bool(found.languages) and not layout.gets_c_family_checks, found.name)

    def test_matching_checks_run(self) -> None:
        context = make_context(FIXTURES / "well_configured")
        self.assertEqual(run_check(_check("cpp", frozenset({"C++"})), context).status, Status.PASS)

    def test_every_check_runs_when_no_language_is_recognised(self) -> None:
        with temp_project({"README.md": ""}) as root:
            self.assertEqual(run_check(_check("cpp", C_FAMILY), make_context(root)).status, Status.PASS)

    def test_builtin_compiler_checks_declare_c_family(self) -> None:
        languages = {found.name: found.languages for found in discover().checks}
        compiler_checks = (
            "ci-build-types", "compiler-warnings", "coverage", "ctest-runs", "cxx-extensions", "platform-matrix"
        )
        for name in compiler_checks:
            self.assertEqual(languages[name], C_FAMILY, name)
        for name in ("ci-present", "security-scanning"):
            self.assertEqual(languages[name], frozenset(), name)
