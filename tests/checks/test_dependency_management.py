import shutil
import unittest
from collections.abc import Mapping

from project_validator.checks.dependency_management import VENDOR_HINT, dependency_management
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp.dependencies import DEPENDENCIES as C_AND_CXX_DEPENDENCIES
from project_validator.ecosystems.go import DEPENDENCIES as GO_DEPENDENCIES
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.python import DEPENDENCIES as PYTHON_DEPENDENCIES
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import DEPENDENCIES as RUST_DEPENDENCIES
from project_validator.ecosystems.rust import RUST
from tests.support import (
    FIXTURES,
    WELL_CONFIGURED,
    make_context,
    run_as,
    run_in_every_layout,
    temp_project,
)
from tests.test_project import git

C_HINT = C_AND_CXX_DEPENDENCIES.hint
NO_DEPENDENCIES = Result.passed("no dependencies are declared")


def _run_in_git(files: Mapping[str, str], tracked: tuple[str, ...]) -> Result:
    with temp_project(files) as root:
        git(root, "init", "-q")
        git(root, "add", *tracked)
        return dependency_management.run(make_context(root))


class DependencyManagementTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertLessEqual(C_FAMILY | {"Python", "Rust", "Go"}, dependency_management.languages)

    def test_the_fixtures(self) -> None:
        cases = {
            "well_configured_c_cpp": Result.passed("dependencies are managed with FetchContent"),
            "well_configured_python": Result.passed(
                "dependencies are declared in pyproject.toml and locked in uv.lock"
            ),
            "well_configured_rust": NO_DEPENDENCIES,
            "well_configured_go": NO_DEPENDENCIES,
        }
        for fixture, expected in cases.items():
            with self.subTest(fixture):
                self.assertEqual(dependency_management.run(make_context(FIXTURES / fixture)), expected)
        for fixture in ("bare_c_cpp", "bare_python", "bare_rust", "bare_go"):
            with self.subTest(fixture):
                self.assertEqual(dependency_management.run(make_context(FIXTURES / fixture)).status, Status.WARN)


class VendoringTests(unittest.TestCase):
    def test_committed_third_party_code_warns(self) -> None:
        for directory in ("third_party", "third-party", "3rdparty", "external", "extern", "vendor"):
            with self.subTest(directory):
                result = run_in_every_layout(self, dependency_management, {f"{directory}/lib/lib.c": ""})
                expected = Result.warned(
                    f"third-party code is committed ({directory}/); no dependencies are declared", C_HINT, VENDOR_HINT
                )
                self.assertEqual(result, expected)

    def test_git_submodules_warn(self) -> None:
        result = run_in_every_layout(self, dependency_management, {**WELL_CONFIGURED, ".gitmodules": ""})
        expected = Result.warned(
            "third-party code is committed (git submodules (.gitmodules)); dependencies are managed with FetchContent",
            VENDOR_HINT,
        )
        self.assertEqual(result, expected)

    def test_a_file_named_like_a_vendor_directory_is_not_one(self) -> None:
        self.assertEqual(run_in_every_layout(self, dependency_management, {"vendor": ""}).status, Status.PASS)

    def test_go_mod_vendor_output_is_not_vendored_code(self) -> None:
        files = {"go.mod": "module m\n", "go.sum": "", "vendor/modules.txt": "", "vendor/x/y.go": ""}
        self.assertEqual(run_as(self, dependency_management, files, GO), NO_DEPENDENCIES)

    def test_a_vendor_directory_without_modules_txt_is_vendored(self) -> None:
        result = run_as(self, dependency_management, {"go.mod": "module m\n", "vendor/x/y.go": ""}, GO)
        self.assertEqual(result.status, Status.WARN)


class CAndCxxTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, dependency_management, files)

    def test_passes_with_a_note_without_a_dependency_manager(self) -> None:
        self.assertEqual(self._run({}), Result.passed("no dependencies are declared", C_HINT))

    def test_names_every_dependency_manager(self) -> None:
        files = {
            "cmake/CPM.cmake": "",
            "cmake/deps.cmake": "CPMAddPackage(NAME fmt GITHUB_REPOSITORY fmtlib/fmt GIT_TAG 11.0.2)\n",
            "vcpkg.json": "{}",
            "conanfile.txt": "",
            "subprojects/zlib.wrap": "",
        }
        expected = Result.passed("dependencies are managed with CPM, vcpkg, Conan and Meson wraps")
        self.assertEqual(self._run(files), expected)


class PythonTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, dependency_management, files, PYTHON)

    def test_warns_when_declared_dependencies_are_not_locked(self) -> None:
        cases = {
            "pyproject.toml": {"pyproject.toml": "[project]\ndependencies = ['requests']\n"},
            "setup.py": {"setup.py": "setup(install_requires=['requests'])\n"},
            "requirements.txt": {"requirements.txt": "requests==2.32.3\n"},
        }
        for where, files in cases.items():
            with self.subTest(where):
                expected = Result.warned(
                    f"dependencies are declared in {where} but not locked", PYTHON_DEPENDENCIES.lock_hint
                )
                self.assertEqual(self._run(files), expected)

    def test_poetry_dependencies_besides_python_are_declared(self) -> None:
        poetry = "[tool.poetry.dependencies]\npython = '^3.12'\nrequests = '^2'\n"
        self.assertEqual(self._run({"pyproject.toml": poetry}).status, Status.WARN)
        python_only = "[tool.poetry.dependencies]\npython = '^3.12'\n"
        self.assertEqual(self._run({"pyproject.toml": python_only}), NO_DEPENDENCIES)

    def test_lockfiles_lock_them(self) -> None:
        for lockfile in ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock", "pylock.toml", "pylock.dev.toml"):
            with self.subTest(lockfile):
                result = self._run({"pyproject.toml": "[project]\ndependencies = ['x']\n", lockfile: ""})
                expected = f"dependencies are declared in pyproject.toml and locked in {lockfile}"
                self.assertEqual(result, Result.passed(expected))

    def test_hash_pinned_requirements_lock_them(self) -> None:
        pinned = (
            "requests==2.32.3 \\\n    --hash=sha256:70761cfe03c773ceb22aa2f671b4757976145175cdfca038c02654d061d6dcc6\n"
        )
        one = self._run({"requirements.txt": pinned})
        self.assertEqual(
            one, Result.passed("dependencies are declared in requirements.txt and locked in requirements.txt")
        )
        several = self._run({"requirements/dev.txt": pinned, "requirements/docs.txt": pinned})
        self.assertEqual(several.message.rpartition(" and locked in ")[2], "2 hash-pinned requirements files")


class RustTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        """Rust layouts build a binary, so these projects are written out whole."""
        with temp_project(files) as root:
            context = make_context(root)
            self.assertEqual(context.structure.languages, RUST.languages)
            return dependency_management.run(context)

    def test_a_library_need_not_commit_cargo_lock(self) -> None:
        files = {"Cargo.toml": "[package]\nname = 'x'\n\n[dependencies]\nlibc = '0.2'\n", "src/lib.rs": ""}
        self.assertEqual(self._run(files), Result.passed("dependencies are managed with Cargo"))

    def test_a_binary_commits_cargo_lock(self) -> None:
        manifest = "[package]\nname = 'x'\n\n[dev-dependencies]\nproptest = '1'\n"
        binaries = {
            "src/main.rs": {"src/main.rs": ""},
            "src/bin": {"src/bin/tool.rs": ""},
            "[[bin]]": {"Cargo.toml": manifest + "\n[[bin]]\nname = 'tool'\npath = 'tool.rs'\n"},
        }
        for binary, files in binaries.items():
            with self.subTest(binary):
                result = self._run({"Cargo.toml": manifest, **files})
                expected = Result.warned(
                    "dependencies are managed with Cargo but not locked", RUST_DEPENDENCIES.lock_hint
                )
                self.assertEqual(result, expected)
                locked = self._run({"Cargo.toml": manifest, **files, "Cargo.lock": ""})
                self.assertEqual(locked, Result.passed("dependencies are managed with Cargo and locked in Cargo.lock"))

    def test_workspace_dependencies_are_managed(self) -> None:
        files = {
            "Cargo.toml": "[workspace]\nmembers = ['a']\n\n[workspace.dependencies]\nserde = '1'\n",
            "a/src/lib.rs": "",
        }
        self.assertEqual(self._run(files), Result.passed("dependencies are managed with Cargo"))

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_an_untracked_cargo_lock_is_not_committed(self) -> None:
        files = {"Cargo.toml": "[dependencies]\nlibc = '0.2'\n", "src/main.rs": "", "Cargo.lock": ""}
        self.assertEqual(_run_in_git(files, ("Cargo.toml", "src")).status, Status.WARN)
        self.assertEqual(_run_in_git(files, ("Cargo.toml", "src", "Cargo.lock")).status, Status.PASS)


class GoTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, dependency_management, files, GO)

    def test_required_modules_need_go_sum(self) -> None:
        go_mod = "module m\n\ngo 1.23\n\nrequire (\n\tgolang.org/x/text v0.14.0\n)\n"
        expected = Result.warned("dependencies are managed with Go modules but not locked", GO_DEPENDENCIES.lock_hint)
        self.assertEqual(self._run({"go.mod": go_mod}), expected)
        locked = Result.passed("dependencies are managed with Go modules and locked in go.sum")
        self.assertEqual(self._run({"go.mod": go_mod, "go.sum": ""}), locked)

    def test_a_module_without_requirements_has_no_dependencies(self) -> None:
        self.assertEqual(self._run({"go.mod": "module m\n"}), NO_DEPENDENCIES)
        self.assertEqual(self._run({"main.go": "package main\n"}), NO_DEPENDENCIES)
