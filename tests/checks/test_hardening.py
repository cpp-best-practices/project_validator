import unittest

from project_validator.checks.hardening import hardening
from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)

GCC_FLAGS = (
    "-D_FORTIFY_SOURCE=3 -D_GLIBCXX_ASSERTIONS -fstack-protector-strong -fcf-protection -fstack-clash-protection"
)
GCC_OPTIONS = (
    "_FORTIFY_SOURCE, -fstack-protector-strong, -fcf-protection, -fstack-clash-protection, "
    "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE"
)
MSVC_OPTIONS = "/sdl, /guard:cf, /DYNAMICBASE, /CETCOMPAT"
MSVC_CI = "jobs:\n  build:\n    runs-on: windows-latest\n    steps:\n      - run: cmake -S . -B build\n"
CLANG_CI = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    env:\n      CXX: clang++\n    steps:\n      - run: make\n"
LINUX_CI = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n"


class HardeningTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(hardening.languages, C_FAMILY | {"Python", "Rust"})


class CAndCxxHardeningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, hardening, files)

    def test_fails_when_no_hardening_options_are_found(self) -> None:
        self.assertEqual(
            self._run(BARE_PROJECT),
            Result.failed(f"no hardening options found; enable -fhardened (GCC 14+) or {GCC_OPTIONS}"),
        )

    def test_failure_lists_msvc_options_when_msvc_is_in_ci(self) -> None:
        self.assertEqual(
            self._run({GITHUB_WORKFLOW: MSVC_CI}),
            Result.failed(
                f"no hardening options found; enable -fhardened (GCC 14+) or {GCC_OPTIONS}, and for MSVC {MSVC_OPTIONS}"
            ),
        )

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.PASS)

    def test_passes_with_every_gcc_and_clang_option_in_any_ci(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: f"script: cmake -S . -B build -DCMAKE_CXX_FLAGS='{GCC_FLAGS}'\n"})
                self.assertEqual(result, Result.passed(f"hardening options are enabled: {GCC_OPTIONS}"))

    def test_options_in_cmake_presets_count(self) -> None:
        preset = f'{{"configurePresets": [{{"cacheVariables": {{"CMAKE_CXX_FLAGS": "{GCC_FLAGS}"}}}}]}}\n'
        for name in ("CMakePresets.json", "CMakeUserPresets.json"):
            with self.subTest(name):
                self.assertEqual(self._run({name: preset}).status, Status.PASS)

    def test_cmake_template_style_passes(self) -> None:
        result = self._run(
            {
                "cmake/Hardening.cmake": """\
                    set(NEW_CXX_DEFINITIONS "${NEW_CXX_DEFINITIONS} -D_GLIBCXX_ASSERTIONS")
                    set(NEW_COMPILE_OPTIONS "${NEW_COMPILE_OPTIONS} -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3")
                    check_cxx_compiler_flag(-fstack-protector-strong STACK_PROTECTOR)
                    set(NEW_COMPILE_OPTIONS "${NEW_COMPILE_OPTIONS} -fcf-protection")
                    set(NEW_COMPILE_OPTIONS "${NEW_COMPILE_OPTIONS} -fstack-clash-protection")
                """,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_libcxx_hardening_mode_counts_as_library_assertions(self) -> None:
        for mode in ("FAST", "EXTENSIVE", "DEBUG"):
            with self.subTest(mode):
                flags = GCC_FLAGS.replace(
                    "-D_GLIBCXX_ASSERTIONS", f"-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_{mode}"
                )
                self.assertEqual(self._run({"CMakeLists.txt": f"add_compile_options({flags})\n"}).status, Status.PASS)

    def test_warns_and_lists_missing_options(self) -> None:
        self.assertEqual(
            self._run({"CMakeLists.txt": "add_compile_options(-fstack-protector-strong)\n"}),
            Result.warned(
                "missing hardening options: _FORTIFY_SOURCE, -fcf-protection, -fstack-clash-protection, "
                "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE",
                "found -fstack-protector-strong",
            ),
        )

    def test_disabled_options_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    add_compile_options(-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fcf-protection=none)
                    add_compile_options(-fno-stack-protector -fno-stack-clash-protection -fno-hardened)
                    add_compile_definitions(_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_NONE)
                """,
            }
        )
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_options_do_not_count(self) -> None:
        self.assertEqual(self._run({"CMakeLists.txt": f"# add_compile_options({GCC_FLAGS})\n"}).status, Status.FAIL)

    def test_fhardened_enables_every_gcc_option(self) -> None:
        self.assertEqual(
            self._run({"CMakeLists.txt": "add_compile_options(-fhardened)\n"}),
            Result.passed("hardening options are enabled: -fhardened"),
        )

    def test_fhardened_alone_warns_when_clang_is_in_ci(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-fhardened)\n", GITHUB_WORKFLOW: CLANG_CI})
        self.assertEqual(
            result,
            Result.warned(
                f"-fhardened is GCC-only; Clang in CI is missing hardening options: {GCC_OPTIONS}", "found -fhardened"
            ),
        )

    def test_fhardened_with_explicit_options_passes_when_clang_is_in_ci(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
                      add_compile_options(-fhardened)
                    else()
                      add_compile_options({GCC_FLAGS})
                    endif()
                """,
                GITHUB_WORKFLOW: CLANG_CI,
            }
        )
        self.assertEqual(result, Result.passed(f"hardening options are enabled: -fhardened, {GCC_OPTIONS}"))

    def test_msvc_in_ci_requires_msvc_options(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n", GITHUB_WORKFLOW: MSVC_CI})
        self.assertEqual(result, Result.warned(f"missing hardening options: {MSVC_OPTIONS}", f"found {GCC_OPTIONS}"))

    def test_msvc_in_ci_passes_with_msvc_options(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(MSVC)
                      add_compile_options(/sdl /guard:cf)
                      add_link_options(/dynamicbase /CETCOMPAT)
                    else()
                      add_compile_options({GCC_FLAGS})
                    endif()
                """,
                GITHUB_WORKFLOW: MSVC_CI,
            }
        )
        self.assertEqual(result, Result.passed(f"hardening options are enabled: {GCC_OPTIONS}, {MSVC_OPTIONS}"))

    def test_disabled_msvc_options_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n"
                "add_compile_options(/sdl- /guard:cf- /DYNAMICBASE:NO /CETCOMPAT:NO)\n",
                GITHUB_WORKFLOW: MSVC_CI,
            }
        )
        self.assertEqual(result, Result.warned(f"missing hardening options: {MSVC_OPTIONS}", f"found {GCC_OPTIONS}"))

    def test_msvc_options_are_not_required_without_msvc_in_ci(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n", GITHUB_WORKFLOW: LINUX_CI})
        self.assertEqual(result.status, Status.PASS)

    def test_only_unrequired_msvc_options_warn_rather_than_fail(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(/sdl /guard:cf)\n"})
        self.assertEqual(result, Result.warned(f"missing hardening options: {GCC_OPTIONS}", "found "))


class PythonHardeningTests(unittest.TestCase):
    OPTIONS = "bandit security lints, hash-checked dependencies"
    HASHES = "run: pip install --require-hashes -r requirements.txt\n"

    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, hardening, files, PYTHON)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(
            self._run(dict(WELL_CONFIGURED_PYTHON)), Result.passed(f"hardening options are enabled: {self.OPTIONS}")
        )

    def test_fails_without_hardening(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: pip install bandit ruff && ruff check --select SIM\n"})
        self.assertEqual(result, Result.failed(f"no hardening options found; enable {self.OPTIONS}"))

    def test_security_lints_in_any_spelling_count(self) -> None:
        spellings = {
            "bandit": {GITHUB_WORKFLOW: "run: python -m bandit -r src\n"},
            "bandit action": {GITHUB_WORKFLOW: "uses: PyCQA/bandit-action@v1\n"},
            "pre-commit bandit": {".pre-commit-config.yaml": "repos:\n  - hooks:\n      - id: bandit\n"},
            "ruff --select": {GITHUB_WORKFLOW: "run: ruff check --select E,S .\n"},
            "ruff --extend-select": {GITHUB_WORKFLOW: "run: ruff check --extend-select=S603 .\n"},
            "pyproject select": {"pyproject.toml": '[tool.ruff.lint]\nselect = ["E", "S"]\n'},
            "pyproject ALL": {"pyproject.toml": "[tool.ruff.lint]\nselect = ['ALL']\n"},
            "ruff.toml extend-select": {"ruff.toml": '[lint]\nextend-select = ["S"]\n'},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                self.assertEqual(
                    self._run({**files, ".github/workflows/deps.yml": self.HASHES}),
                    Result.passed(f"hardening options are enabled: {self.OPTIONS}"),
                )

    def test_hash_checked_dependencies_in_any_spelling_count(self) -> None:
        for command in ("pip-compile --generate-hashes", "uv sync --locked", "uv sync --frozen --all-extras"):
            with self.subTest(command):
                result = self._run({GITHUB_WORKFLOW: f"run: {command} && bandit -r .\n"})
                self.assertEqual(result.status, Status.PASS)

    def test_hardening_in_any_ci_counts(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: f"script: bandit -r src && {self.HASHES}"})
                self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_options(self) -> None:
        self.assertEqual(
            self._run({GITHUB_WORKFLOW: "run: bandit -r src\n"}),
            Result.warned("missing hardening options: hash-checked dependencies", "found bandit security lints"),
        )

    def test_c_and_cxx_options_do_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)


class RustHardeningTests(unittest.TestCase):
    OPTIONS = "unsafe_code forbidden, release overflow-checks"
    OVERFLOW_CHECKS = "[profile.release]\noverflow-checks = true\n"

    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, hardening, files, RUST)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(
            self._run(dict(WELL_CONFIGURED_RUST)), Result.passed(f"hardening options are enabled: {self.OPTIONS}")
        )

    def test_fails_without_hardening(self) -> None:
        files = {
            "Cargo.toml": "[lints.rust]\nunsafe_code = 'allow'\n\n[profile.dev]\noverflow-checks = true\n",
            GITHUB_WORKFLOW: "run: cargo build -C overflow-checks=off\n",
        }
        self.assertEqual(self._run(files), Result.failed(f"no hardening options found; enable {self.OPTIONS}"))

    def test_forbidding_unsafe_code_in_any_spelling_counts(self) -> None:
        spellings = {
            "Cargo lints": {"Cargo.toml": f'[lints.rust]\nunsafe_code = "forbid"\n\n{self.OVERFLOW_CHECKS}'},
            "Cargo lint table": {
                "Cargo.toml": f"[lints.rust]\nunsafe_code = {{ level = 'deny' }}\n\n{self.OVERFLOW_CHECKS}"
            },
            "workspace member": {
                "crates/core/Cargo.toml": "[lints.rust]\nunsafe_code = 'forbid'\n",
                "Cargo.toml": self.OVERFLOW_CHECKS,
            },
            "crate attribute": {"src/main.rs": "#![forbid(unsafe_code)]\n", "Cargo.toml": self.OVERFLOW_CHECKS},
            "library attribute": {
                "src/lib.rs": "#![deny(missing_docs, unsafe_code)]\n",
                "Cargo.toml": self.OVERFLOW_CHECKS,
            },
            "rustflags": {
                ".cargo/config.toml": '[build]\nrustflags = ["-F", "unsafe_code", "-C", "overflow-checks"]\n'
            },
            "command line": {GITHUB_WORKFLOW: "run: cargo rustc -- --forbid unsafe_code -Coverflow-checks=on\n"},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                self.assertEqual(self._run(files), Result.passed(f"hardening options are enabled: {self.OPTIONS}"))

    def test_module_level_unsafe_code_lints_do_not_count(self) -> None:
        result = self._run({"src/lib.rs": "#[forbid(unsafe_code)]\nmod safe {}\n", "Cargo.toml": self.OVERFLOW_CHECKS})
        self.assertEqual(
            result, Result.warned("missing hardening options: unsafe_code forbidden", "found release overflow-checks")
        )

    def test_overflow_checks_outside_the_release_profile_do_not_count(self) -> None:
        result = self._run(
            {"Cargo.toml": "[profile.dev]\noverflow-checks = true\n", "src/lib.rs": "#![forbid(unsafe_code)]\n"}
        )
        self.assertEqual(
            result, Result.warned("missing hardening options: release overflow-checks", "found unsafe_code forbidden")
        )

    def test_c_and_cxx_options_do_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)


class MixedLanguageHardeningTests(unittest.TestCase):
    def test_every_language_needs_hardening_and_findings_are_labelled(self) -> None:
        result = run_as(self, hardening, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertTrue(result.message.startswith("C/C++: hardening options are enabled: _FORTIFY_SOURCE"))
        self.assertTrue(
            result.message.endswith(
                "; Python: no hardening options found; enable bandit security lints, hash-checked dependencies"
            )
        )
