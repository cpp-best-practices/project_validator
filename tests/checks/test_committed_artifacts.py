from __future__ import annotations

import shutil
import unittest
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.c_family.build import BUILD_DIRECTORY
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.core import Context, Options, Project, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.go import BUILD_OUTPUTS
from project_validator.ecosystems.python import BYTECODE
from project_validator.ecosystems.rust import TARGET_DIRECTORY
from project_validator.policy.outputs import COMMITTED_HINT as HINT
from tests.support import FIXTURES, make_context, temp_project
from tests.test_project import git

PASSED = Result.passed("no build outputs are committed")


def _run(files: Mapping[str, str], *, tracked: tuple[str, ...] = (), exclude: str = "") -> Result:
    with temp_project(files) as root:
        if tracked:
            git(root, "init", "-q")
            git(root, "add", *tracked)
        project = Project(root, frozenset({PurePosixPath(exclude)} if exclude else ()))
        return committed_artifacts.run(Context(project, make_context(root).providers, Options()))


class ArtifactTests(unittest.TestCase):
    def test_file_globs_match_a_file_name_at_any_depth(self) -> None:
        self.assertEqual(BUILD_DIRECTORY.artifact("src/deep/main.o"), "src/deep/main.o")
        self.assertEqual(BUILD_DIRECTORY.artifact("lib/libz.so.1"), "lib/libz.so.1")
        self.assertIsNone(BUILD_DIRECTORY.artifact("src/main.cpp"))
        self.assertIsNone(BUILD_DIRECTORY.artifact("docs/o.md"))

    def test_directory_globs_name_the_directory(self) -> None:
        self.assertEqual(BYTECODE.artifact("pkg/__pycache__/m.cpython-314.pyc"), "pkg/__pycache__/")
        self.assertEqual(BYTECODE.artifact("src/demo.egg-info/PKG-INFO"), "src/demo.egg-info/")
        self.assertEqual(BUILD_DIRECTORY.artifact("cmake-build-debug/x/CMakeCache.txt"), "cmake-build-debug/")

    def test_rooted_directory_globs_match_only_at_the_top(self) -> None:
        self.assertEqual(TARGET_DIRECTORY.artifact("target/debug/app"), "target/")
        self.assertIsNone(TARGET_DIRECTORY.artifact("src/target/mod.rs"))
        self.assertIsNone(TARGET_DIRECTORY.artifact("target"))
        self.assertEqual(BUILD_OUTPUTS.artifact("bin/app"), "bin/")
        self.assertIsNone(BUILD_OUTPUTS.artifact("tools/bin/run.sh"))

    def test_a_directory_glob_does_not_match_a_file_of_that_name(self) -> None:
        self.assertIsNone(BYTECODE.artifact("__pycache__"))


class CommittedArtifactsTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertLessEqual(C_FAMILY | {"Python", "Rust", "Go"}, committed_artifacts.languages)

    def test_passes_with_the_well_configured_fixtures(self) -> None:
        for fixture in (
            "well_configured_cpp",
            "well_configured_python",
            "well_configured_rust",
            "well_configured_go",
        ):
            with self.subTest(fixture=fixture):
                self.assertEqual(committed_artifacts.run(make_context(FIXTURES / fixture)), PASSED)

    def test_fails_with_the_bare_fixtures(self) -> None:
        for fixture in ("bare_cpp", "bare_python", "bare_rust", "bare_go"):
            with self.subTest(fixture=fixture):
                self.assertEqual(committed_artifacts.run(make_context(FIXTURES / fixture)).status, Status.FAIL)

    def test_outside_a_checkout_every_file_counts_as_committed_build_trees_too(self) -> None:
        """A project that is no git checkout (a tarball, or mutmut's copy inside a checkout that ignores it) has every
        file counted as committed: a build tree, which the project's files leave out, is among them."""
        with temp_project({"Cargo.toml": "", "src/main.rs": "", "target/debug/bare": ""}) as root:
            self.assertEqual(committed_artifacts.run(make_context(root)).status, Status.FAIL)

    def test_fails_listing_each_output_once(self) -> None:
        files = {"CMakeLists.txt": "", "main.cpp": "", "build/a.o": "", "build/b.o": "", "src/x.obj": ""}
        expected = Result.failed("2 build outputs are committed", "build/", "src/x.obj", HINT)
        self.assertEqual(_run(files), expected)

    def test_one_output(self) -> None:
        self.assertEqual(
            _run({"go.mod": "", "app.test": ""}), Result.failed("1 build output is committed", "app.test", HINT)
        )

    def test_lists_at_most_five(self) -> None:
        files = {"CMakeLists.txt": "", **{f"o{index}.o": "" for index in range(7)}}
        result = _run(files)
        self.assertEqual(result.message, "7 build outputs are committed")
        self.assertEqual(result.details, (*(f"o{index}.o" for index in range(5)), "and 2 more", HINT))

    def test_labels_each_ecosystem(self) -> None:
        result = _run({"pyproject.toml": "", "dist/x.whl": "", "Cargo.toml": "", "src/main.rs": ""})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.message, "Python: 1 build output is committed; Rust: no build outputs are committed")

    def test_honours_excludes(self) -> None:
        self.assertEqual(_run({"CMakeLists.txt": "", "tests/fixtures/a.o": ""}, exclude="tests/fixtures"), PASSED)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_only_tracked_files_are_judged_in_a_git_checkout(self) -> None:
        files = {"Cargo.toml": "", "src/main.rs": "", "target/debug/app": "", "local.o": ""}
        self.assertEqual(_run(files, tracked=("Cargo.toml", "src")), PASSED)
        expected = Result.failed("1 build output is committed", "target/", HINT)
        self.assertEqual(_run(files, tracked=("Cargo.toml", "src", "target")), expected)


class BinaryOutputTests(unittest.TestCase):
    def test_a_file_named_like_a_binary_is_one_only_when_it_holds_binary_data(self) -> None:
        sources = {"CMakeLists.txt": "project(x)\n", "a.cpp": ""}
        binary = _run({**sources, "tool.exe": "MZ\0\0"})
        self.assertEqual(binary.status, Status.FAIL)
        self.assertIn("tool.exe", binary.details)
        self.assertEqual(_run({**sources, "tool.exe": "#!/bin/sh\nexec x\n"}), PASSED)


class PlaceholderTests(unittest.TestCase):
    def test_a_directory_holding_only_placeholders_is_no_committed_output(self) -> None:
        """cmake_template keeps gcovr's report directory with an empty out/coverage/.keep: nothing built is
        committed (#235). A real output beside the placeholder still is."""
        sources = {"CMakeLists.txt": "project(x)\n", "a.cpp": ""}
        for placeholder in ("out/coverage/.keep", "build/.gitkeep", "out/.gitignore"):
            with self.subTest(placeholder=placeholder):
                self.assertEqual(_run({**sources, placeholder: ""}), PASSED)
        result = _run({**sources, "out/.gitkeep": "", "out/app.o": "\0"})
        self.assertEqual(result.status, Status.FAIL)

    def test_what_a_build_writes_beside_sources_of_other_languages_is_still_an_output(self) -> None:
        """A wheel in a Python dist/, beside a packaging script, and a binary in a Go bin/, beside a shell script, are
        what the builds write (#235): the sources of other languages do not make those directories sources."""
        python = {"pyproject.toml": "[project]\nname = 'p'\n", "p.py": ""}
        go = {"go.mod": "module example.com/x\n", "main.go": "package main\n"}
        cases = {
            "wheel": {**python, "dist/p-1.0-py3-none-any.whl": "PK\0", "dist/release.sh": "#!/bin/sh\n"},
            "binary": {**go, "bin/x": "\x7fELF\0", "bin/x.go": "package main\n"},
            "binary beside a script": {**go, "bin/x": "\x7fELF\0", "bin/run.sh": "#!/bin/sh\n"},
        }
        for name, files in cases.items():
            with self.subTest(name):
                self.assertEqual(_run(files).status, Status.FAIL)


class OwnerUnitTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_an_output_counts_for_a_language_of_the_unit_that_holds_it(self) -> None:
        """Humanizer's src/Humanizer.Analyzers/build/ holds NuGet's MSBuild targets in a .NET project: it is not the
        Docusaurus site's build/, which website/ would write (#235)."""
        files = {
            "website/docusaurus.config.js": "module.exports = {};\n",
            "website/docs/intro.md": "# Intro\n",
            "website/package.json": '{"dependencies": {"@docusaurus/core": "3.0.0"}}\n',
            "src/Foo.Analyzers/Foo.Analyzers.csproj": "<Project Sdk='Microsoft.NET.Sdk'></Project>\n",
            "src/Foo.Analyzers/A.cs": "class A {}\n",
            "src/Foo.Analyzers/build/Foo.targets": "<Project></Project>\n",
        }
        result = _run(files)
        self.assertNotIn("src/Foo.Analyzers/build/", " ".join((result.message, *result.details)), result)
        # A language's output counts wherever it is: tidyall's committed node_modules/ at a Perl root, though its
        # JavaScript is a vendored PHP tool's.
        perl = {"Makefile.PL": "", "lib/A.pm": "", "tools/js/package.json": "{}\n", "tools/js/a.js": ""}
        vendored = {**perl, "node_modules/x/index.js": "", "node_modules/x/package.json": "{}\n"}
        committed = _run(vendored, tracked=tuple(vendored))
        self.assertIn("JavaScript: node_modules/", committed.details, committed)
        site = {"docusaurus.config.js": "module.exports = {};\n", "package.json": "{}\n"}
        built = _run({**files, **site, "build/index.html": "<html></html>\n"})
        self.assertIn("Documentation site: build/", built.details, built)
