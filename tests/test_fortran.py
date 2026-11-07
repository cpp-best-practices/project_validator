"""The Fortran profile: recognition, fpm, and the Fortran compilers' flags, judged by the generic checks in every
Fortran project layout; and the shared CMake and Meson facts, which scope options to Fortran."""

import unittest

from project_validator.build_systems.cmake.build import cmake_declared_languages
from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.checks.hardening import hardening
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.fortran import FORTRAN_ECOSYSTEM, FPM_SETTINGS, fpm_build_types
from project_validator.facts import Setting
from project_validator.facts.outputs import known_build_outputs
from tests.support import command, github_job, github_steps, make_context, run_as, run_in_layout, temp_project

FORTRAN = frozenset({"Fortran"})
STRICT = "-Wall -Wextra -Wpedantic -Wimplicit-interface"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_sources_of_every_form_are_fortran(self) -> None:
        for source in ("main.f90", "legacy.f", "LEGACY.FOR", "pre.F90", "kinds.fypp", "new.f18"):
            with self.subTest(source=source), temp_project({source: ""}) as root:
                self.assertEqual(make_context(root).structure.languages, FORTRAN)

    def test_cmake_builds_the_languages_its_project_enables(self) -> None:
        cases = {
            "project(app LANGUAGES Fortran)": FORTRAN,
            "project(app VERSION 1.0 LANGUAGES C Fortran)": FORTRAN | {"C"},
            "project(app Fortran CXX)": FORTRAN | {"C++"},
            "project(app)": C_FAMILY,
            "project(app VERSION 2.0)": C_FAMILY,
            "project(app NONE)\nenable_language(Fortran)": FORTRAN,
            "project(app NONE)\nenable_language(${LANGUAGE})": C_FAMILY,
            # After another keyword's value, languages are listed only after LANGUAGES.
            "project(app VERSION 1.0 Fortran)": C_FAMILY,
            "project(app LANGUAGES ${LANGS})": C_FAMILY,
            "project(": C_FAMILY,
        }
        for text, languages in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cmake_declared_languages("CMakeLists.txt", text), languages)

    def test_only_the_top_level_cmake_file_has_an_implicit_project(self) -> None:
        self.assertEqual(cmake_declared_languages("CMakeLists.txt", "add_executable(app main.f90)"), C_FAMILY)
        self.assertEqual(cmake_declared_languages("src/CMakeLists.txt", "add_executable(app main.f90)"), frozenset())

    def test_a_fortran_cmake_project_is_not_a_c_project(self) -> None:
        files = {"CMakeLists.txt": "project(app LANGUAGES Fortran)\nadd_subdirectory(src)\n"}
        files |= {"src/CMakeLists.txt": "add_executable(app main.f90)\n", "src/main.f90": ""}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.languages, FORTRAN)

    def test_meson_declares_fortran(self) -> None:
        with temp_project({"meson.build": "project('app', 'fortran')\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, FORTRAN)

    def test_fpm_manifests_are_read(self) -> None:
        settings = list(FPM_SETTINGS.read("fpm.toml", 'name = "app"\n[build]\nauto-tests = false\n'))
        read = [(setting.key, setting.value) for setting in settings if isinstance(setting, Setting)]
        self.assertIn(("build.auto-tests", False), read)


class FortranTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, FORTRAN_ECOSYSTEM)

    def _fpm(self, selected: Check, files: dict[str, str]) -> Result:
        """In an fpm package, which (unlike Meson, whose default warning level passes -Wall) sets no flags."""
        return run_in_layout(self, "fpm package", selected, files)

    def test_strict_warnings_on_the_command_line(self) -> None:
        passed = self._fpm(compiler_warnings, _ci(f"gfortran {STRICT} -c src/app.f90"))
        self.assertEqual(passed, Result.passed(f"strict Fortran compiler warning flags are enabled: {STRICT}"))
        warned = self._fpm(compiler_warnings, _ci("gfortran -Wall -c src/app.f90"))
        self.assertEqual(warned.status, Status.WARN)
        self.assertIn("-Wimplicit-interface", warned.message)

    def test_fpm_builds_with_its_debug_profile_unless_given_flags(self) -> None:
        default = self._fpm(compiler_warnings, _ci("fpm test"))
        self.assertEqual(default, Result.warned("missing Fortran compiler warning flags: -Wpedantic", ANY_FOUND))
        overridden = self._fpm(compiler_warnings, _ci('fpm test --flag "-O2"'))
        self.assertEqual(overridden.status, Status.FAIL)
        added = self._fpm(compiler_warnings, _ci('fpm test --profile debug --flag "-Wpedantic"'))
        self.assertEqual(added.status, Status.PASS)
        self.assertEqual(self._fpm(compiler_warnings, _ci("fpm test --profile release")).status, Status.WARN)

    def test_each_compiler_ci_builds_with_is_asked_for_its_own_flags(self) -> None:
        files = github_steps(
            "uses: fortran-lang/setup-fortran@v1", f"run: gfortran {STRICT} -Werror -c a.f90", "run: ifx -c a.f90"
        )
        result = self._fpm(compiler_warnings, files)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("-warn all for intel", result.message)
        intel = self._run(warnings_as_errors, _ci("ifx -warn all -warn errors -c a.f90"))
        self.assertEqual(intel, Result.passed("warnings are treated as errors with -warn errors"))

    def test_a_standard_disables_the_dialects(self) -> None:
        self.assertEqual(self._run(cxx_extensions, _ci("gfortran -std=f2018 -c a.f90")).status, Status.PASS)
        self.assertEqual(self._run(cxx_extensions, _ci("gfortran -std=gnu -c a.f90")).status, Status.FAIL)
        self.assertEqual(self._run(cxx_extensions, _ci("ifx -stand f18 -c a.f90")).status, Status.PASS)

    def test_hardening_asks_for_the_back_end_protections(self) -> None:
        self.assertEqual(self._run(hardening, _ci("gfortran -fhardened -c a.f90")).status, Status.PASS)
        result = self._run(hardening, _ci("gfortran -fstack-protector-strong -D_FORTIFY_SOURCE=3 -c a.f90"))
        self.assertEqual(result.status, Status.WARN)
        self.assertNotIn("FORTIFY", result.message)

    def test_a_library_is_not_hardened(self) -> None:
        files = {"fpm.toml": 'name = "lib"\n', "src/lib.f90": "module lib\nend module lib\n"}
        with temp_project(files) as root:
            self.assertEqual(hardening.run(make_context(root)).status, Status.SKIP)

    def test_fpm_runs_the_test_programs(self) -> None:
        tests = {"test/check.f90": "program check\nend program check\n"}
        self.assertEqual(self._run(tests_run, {**tests, **_ci("fpm test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, _ci("fpm test")).status, Status.FAIL)

    def test_fpm_profiles_are_build_types(self) -> None:
        self.assertEqual(fpm_build_types(command("fpm test")), frozenset({"debug"}))
        self.assertEqual(fpm_build_types(command("fpm build --profile release")), frozenset({"release"}))
        self.assertEqual(fpm_build_types(command("fpm new app")), frozenset())
        matrix = {"profile": ["debug", "release"], "sanitizers": ["", "-fsanitize=address"]}
        files = github_job(
            "ubuntu-latest", "fpm test --profile ${{ matrix.profile }} --flag '${{ matrix.sanitizers }}'", matrix=matrix
        )
        self.assertEqual(self._run(ci_build_types, files).status, Status.PASS)

    def test_ci_compilers_are_the_fortran_compilers(self) -> None:
        matrix = {"toolchain": [{"compiler": "gcc"}, {"compiler": "intel"}], "os": ["ubuntu-latest", "windows-latest"]}
        files = github_job("${{ matrix.os }}", "fpm test", matrix=matrix)
        result = self._run(platform_matrix, files)
        self.assertIn("2 compiler(s) (gcc, intel)", result.message)

    def test_tools(self) -> None:
        self.assertEqual(self._run(code_formatting, _ci("fprettify --diff -r src")).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("fprettify -r src")).status, Status.FAIL)
        self.assertEqual(self._run(static_analysis, _ci("fortitude check")).status, Status.PASS)


ANY_FOUND = f"found {STRICT.replace(' -Wpedantic', '')}"


class SharedBuildSystemTests(unittest.TestCase):
    def test_cmake_options_count_only_for_the_languages_they_apply_to(self) -> None:
        cmake = "project(app LANGUAGES Fortran)\nadd_compile_options($<$<COMPILE_LANGUAGE:CXX>:-Werror>)\n"
        result = run_in_layout(self, "CMake Fortran", warnings_as_errors, {"CMakeLists.txt": cmake})
        self.assertEqual(result.status, Status.FAIL)
        cmake = "project(app LANGUAGES Fortran)\nset(CMAKE_COMPILE_WARNING_AS_ERROR ON)\n"
        result = run_in_layout(self, "CMake Fortran", warnings_as_errors, {"CMakeLists.txt": cmake})
        self.assertEqual(result.status, Status.PASS)

    def test_cmake_options_for_one_compiler_count_for_it(self) -> None:
        cmake = (
            "project(app LANGUAGES Fortran)\n"
            'if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")\n'
            f"  add_compile_options({STRICT})\n"
            "endif()\n"
        )
        result = run_in_layout(self, "CMake Fortran", compiler_warnings, {"CMakeLists.txt": cmake, **_ci("ctest")})
        self.assertEqual(result.status, Status.PASS)

    def test_meson_warning_levels_pass_gfortran_flags(self) -> None:
        meson = "project('app', 'fortran', default_options: ['warning_level=3', 'fortran_std=f2018'])\n"
        result = run_in_layout(self, "Meson Fortran", compiler_warnings, {"meson.build": meson})
        self.assertEqual(
            result,
            Result.warned(
                "missing Fortran compiler warning flags: -Wimplicit-interface",
                f"found {STRICT.replace(' -Wimplicit-interface', '')}",
            ),
        )
        self.assertEqual(
            run_in_layout(self, "Meson Fortran", cxx_extensions, {"meson.build": meson}).status, Status.PASS
        )
        legacy = "project('app', 'fortran', default_options: ['fortran_std=legacy'])\n"
        result = run_in_layout(self, "Meson Fortran", cxx_extensions, {"meson.build": legacy})
        self.assertEqual(result.status, Status.FAIL)


class ArtifactTests(unittest.TestCase):
    def test_module_files_are_build_output_but_go_mod_is_not(self) -> None:
        [output] = [output for output in known_build_outputs() if output.languages == FORTRAN]
        self.assertEqual(output.artifact("src/app.mod"), "src/app.mod")
        self.assertIsNone(output.artifact("go.mod"))
        self.assertIn("Fortran", committed_artifacts.languages)


if __name__ == "__main__":
    unittest.main()
