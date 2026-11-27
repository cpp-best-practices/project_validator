"""CMake: the project's CMake code (`CMakeLists.txt`, `*.cmake`), a format judged beside the language it builds. The
build system itself is read by `project_validator.build_systems.cmake` for the C and C++ profiles; what is asked of
the CMake code here is hygiene: it is formatted (`code-formatting`: gersemi, cmake-format), linted (`static-analysis`:
cmake-lint, cmakelint), and CMake's own warnings about it fail CI (`warnings-as-errors`: `cmake -Werror=dev`)."""

from __future__ import annotations

import re

from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always, requirement_reader
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by, starts, when

CMAKE = "CMake"
CMAKE_ONLY = frozenset({CMAKE})

CMAKE_ECOSYSTEM = Ecosystem(
    label="CMake",
    links={"CMake": "https://cmake.org/"},
    kind="format",
    languages=CMAKE_ONLY,
    source_suffixes={".cmake": CMAKE},
    source_names={"CMakeLists.txt": CMAKE},
    ci_programs=(("cmake",), ("ctest",), ("gersemi",), ("cmake-format",), ("cmake-lint",), ("cmakelint",)),
)

# --- formatting -----------------------------------------------------------------------------------------------------

# gersemi (fmt-adjacent projects, the CMake community's formatter): `--check` or `--diff` fails on a file it would
# change, `-i` rewrites them; `.gersemirc` sets its style.
GERSEMI_SETTINGS = file_reader("gersemi", (".gersemirc",))
GERSEMI = format_tool(
    name="gersemi",
    languages=CMAKE_ONLY,
    can={Enforcement.CHECK: "gersemi --check .", Enforcement.APPLY: "gersemi -i ."},
    formats=flagged(("gersemi",), checks=("--check", "--diff"), applies=("-i", "--in-place")),
    style=defined_by(files=(GERSEMI_SETTINGS.name,)),
)
# cmake-format (cmakelang; fmt, cmake_template): `--check` fails on a file it would change, `-i` rewrites them; its
# configuration (`.cmake-format.yaml`, `.json`, `.py`) sets the style cmake-lint checks too.
CMAKE_FORMAT_SETTINGS = file_reader(
    "cmake-format",
    (".cmake-format", ".cmake-format.yaml", ".cmake-format.yml", ".cmake-format.json", ".cmake-format.py"),
)
CMAKE_FORMAT = format_tool(
    name="cmake-format",
    languages=CMAKE_ONLY,
    can={Enforcement.CHECK: "cmake-format --check CMakeLists.txt", Enforcement.APPLY: "cmake-format -i CMakeLists.txt"},
    formats=flagged(("cmake-format",), checks=("--check",), applies=("-i", "--in-place")),
    style=defined_by(files=(CMAKE_FORMAT_SETTINGS.name,)),
)

# --- linting --------------------------------------------------------------------------------------------------------

# cmake-lint (cmakelang), configured as cmake-format is; cmakelint (`.cmakelintrc`).
CMAKE_LINT = analyzer(
    name="cmake-lint",
    languages=CMAKE_ONLY,
    how="cmake-lint CMakeLists.txt",
    analyses=when(starts(("cmake-lint",)), analysed),
    rules=defined_by(files=(CMAKE_FORMAT_SETTINGS.name,)),
)
CMAKELINT_SETTINGS = file_reader("cmakelint", (".cmakelintrc",))
CMAKELINT = analyzer(
    name="cmakelint",
    languages=CMAKE_ONLY,
    how="cmakelint CMakeLists.txt",
    analyses=when(starts(("cmakelint",)), analysed),
    rules=defined_by(files=(CMAKELINT_SETTINGS.name,)),
)


# --- warnings as errors ---------------------------------------------------------------------------------------------

# `cmake -Werror=dev` makes CMake's warnings for the project's own code (deprecated commands, policy warnings) errors
# when CI configures the build; a configure preset says so with `errors: {dev: true}`.
WERROR_DEV = Requirement(
    name="cmake -Werror=dev",
    runs=re.compile(r"(?<![\w-])cmake\b.*\s-Werror=dev\b"),
    pattern=re.compile(r'"errors"\s*:\s*\{[^{}]*"dev"\s*:\s*true'),
    hints=("-Werror=dev",),
)
CMAKE_PRESET_ERRORS = requirement_reader("CMake preset errors", ("CMakePresets.json",), (WERROR_DEV,))
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=CMAKE_ONLY,
    requirements=always(WERROR_DEV),
    reads=(CMAKE_PRESET_ERRORS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration and CMakePresets.json",
        hint='configure with cmake -Werror=dev (or a preset\'s "errors": {"dev": true}), so CMake\'s warnings fail CI',
    ),
)
