"""C and C++ are separate languages, each its own ecosystem: a project is judged for the ones its code is written in."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.compiler_extensions import compiler_extensions
from project_validator.core import Status
from project_validator.runner import select
from tests.support import checks_named, make_context, temp_project

CMAKE_DEFAULT = "cmake_minimum_required(VERSION 3.21)\nproject(app)\nadd_executable(app {sources})\n"


def _ecosystems(files: Mapping[str, str]) -> dict[str, list[str]]:
    """Each unit's directory -> the ecosystems the map recognises in it."""
    with temp_project(files) as root:
        structure = make_context(root).structure
        recognised = list(structure.recognised_by)
        return {
            unit.directory: sorted(label for label in recognised if label in _labels(unit.languages))
            for unit in structure.units
        }


def _labels(languages: frozenset[str]) -> set[str]:
    return {language for language in languages if language in {"C", "C++"}}


def _languages(files: Mapping[str, str]) -> list[str]:
    with temp_project(files) as root:
        return sorted(make_context(root).structure.languages)


class EcosystemTests(unittest.TestCase):
    def test_c_sources_make_a_c_project(self) -> None:
        self.assertEqual(_ecosystems({"main.c": "", "util.h": ""}), {".": ["C"]})

    def test_cxx_sources_make_a_cxx_project(self) -> None:
        self.assertEqual(_ecosystems({"main.cpp": "", "util.hpp": ""}), {".": ["C++"]})

    def test_both_kinds_of_source_make_both(self) -> None:
        self.assertEqual(_ecosystems({"main.cpp": "", "legacy.c": ""}), {".": ["C", "C++"]})

    def test_the_labels_name_one_language_each(self) -> None:
        with temp_project({"main.c": "", "main.cpp": ""}) as root:
            self.assertEqual(sorted(make_context(root).structure.recognised_by), ["C", "C++"])


class CMakeDefaultLanguageTests(unittest.TestCase):
    """CMake's project() enables C and C++ unless told otherwise; that says nothing about the code."""

    def test_a_cxx_project_with_the_default_languages_is_cxx(self) -> None:
        files = {"CMakeLists.txt": CMAKE_DEFAULT.format(sources="main.cpp"), "main.cpp": ""}
        self.assertEqual(_languages(files), ["C++"])

    def test_a_c_project_with_the_default_languages_is_c(self) -> None:
        files = {"CMakeLists.txt": CMAKE_DEFAULT.format(sources="main.c"), "main.c": ""}
        self.assertEqual(_languages(files), ["C"])

    def test_a_build_file_without_sources_keeps_what_it_declares(self) -> None:
        files = {"CMakeLists.txt": "project(app LANGUAGES CXX)\n"}
        self.assertEqual(_languages(files), ["C++"])

    def test_the_c_project_is_not_recognised_as_cxx(self) -> None:
        files = {"CMakeLists.txt": CMAKE_DEFAULT.format(sources="main.c"), "main.c": ""}
        with temp_project(files) as root:
            self.assertEqual(list(make_context(root).structure.recognised_by), ["C", "CMake"])


class HeaderTests(unittest.TestCase):
    """A `.h` header is C or C++ by the sources around it: the majority below its nearest ancestor that has any."""

    def test_headers_beside_cxx_sources_are_cxx(self) -> None:
        self.assertEqual(_languages({"src/main.cpp": "", "include/app/app.h": ""}), ["C++"])

    def test_headers_beside_c_sources_are_c(self) -> None:
        self.assertEqual(_languages({"src/main.c": "", "include/app/app.h": ""}), ["C"])

    def test_each_part_of_a_mixed_tree_keeps_its_own_language(self) -> None:
        files = {
            "CMakeLists.txt": "project(app)\nadd_subdirectory(clib)\nadd_subdirectory(app)\n",
            "clib/CMakeLists.txt": "add_library(clib a.c b.c)\n",
            "clib/a.c": "",
            "clib/b.c": "",
            "clib/include/clib.h": "",
            "app/CMakeLists.txt": "add_executable(app main.cpp)\n",
            "app/main.cpp": "",
            "app/app.h": "",
        }
        with temp_project(files) as root:
            facts = make_context(root).facts
            from project_validator.facts.structure import SourceFile

            headers = {source.path: source.language for source in facts.of(SourceFile) if source.path.endswith(".h")}
        self.assertEqual(headers, {"clib/include/clib.h": "C", "app/app.h": "C++"})

    def test_a_header_only_project_is_c_unless_the_build_says_cxx(self) -> None:
        self.assertEqual(_languages({"CMakeLists.txt": "project(lib)\n", "include/lib.h": ""}), ["C"])
        self.assertEqual(_languages({"CMakeLists.txt": "project(lib CXX)\n", "include/lib.h": ""}), ["C++"])


class CompilerExtensionsTests(unittest.TestCase):
    def test_the_check_is_named_for_every_language_it_judges(self) -> None:
        self.assertEqual(compiler_extensions.name, "compiler-extensions")

    def test_the_old_name_still_selects_it(self) -> None:
        self.assertEqual(
            [found.name for found in select(checks_named("compiler-extensions"), ["cxx-extensions"], [])],
            ["compiler-extensions"],
        )


if __name__ == "__main__":
    unittest.main()


class PerLanguageFlagsTests(unittest.TestCase):
    """Each language is judged by its own flags: C++'s do not warn about C, nor C's about C++."""

    def _warnings_as_errors(self, cmake: str) -> dict[str, Status]:
        from project_validator.checks.warnings_as_errors import warnings_as_errors

        files = {"CMakeLists.txt": cmake, "src/main.cpp": "", "src/legacy.c": ""}
        with temp_project(files) as root:
            result = warnings_as_errors.run(make_context(root))
        # The CMake code's own warnings-as-errors is the CMake format's, not a language's.
        return {place.ecosystem: place.result.status for place in result.places if place.ecosystem != "CMake"}

    def test_cxx_flags_count_for_cxx_alone(self) -> None:
        found = self._warnings_as_errors('project(app C CXX)\nset(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Werror")\n')
        self.assertEqual(found, {"C": Status.FAIL, "C++": Status.PASS})

    def test_c_flags_count_for_c_alone(self) -> None:
        found = self._warnings_as_errors('project(app C CXX)\nset(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Werror")\n')
        self.assertEqual(found, {"C": Status.PASS, "C++": Status.FAIL})

    def test_flags_for_every_language_count_for_both(self) -> None:
        found = self._warnings_as_errors("project(app C CXX)\nadd_compile_options(-Werror)\n")
        self.assertEqual(found, {"C": Status.PASS, "C++": Status.PASS})
