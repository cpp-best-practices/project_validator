"""C: built with CMake or Meson, judged by its compilers. C and C++ are separate languages and separate ecosystems,
which share their build systems, CI programs and tools (`project_validator.c_family`); C is judged on its own, with
C's flags (`CMAKE_C_FLAGS`, `c_std`), never C++'s. A project with neither build system is judged as a CMake project.

The shape of a C-family ecosystem (`c_family_ecosystem`) is here, and the C++ profile builds its ecosystem with it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from project_validator.build_systems.cmake.build import CMAKE
from project_validator.build_systems.meson.build import MESON
from project_validator.ecosystems.model import Ecosystem

# Building C or C++, as opposed to running another ecosystem's tools on a runner that has a C or C++ compiler.
# The build tools a CI job builds C or C++ with, and what else in a job shows it does: a source file, a compiler.
CI_PROGRAMS = tuple(
    (program,)
    for program in (
        # Not make, which runs whatever a Makefile says (`make lint` in a Python project), nor devenv alone, which is
        # Nix's devenv too: Visual Studio's names a solution (see CI_USAGE).
        *("cmake", "ctest", "meson", "ninja", "msbuild", "bazel", "conan", "vcpkg"),
        *("xmake", "premake", "premake4", "premake5", "scons"),
    )
)
CI_USAGE = re.compile(
    r"\.(?:c|cc|cpp|cxx)\b|\bg\+\+(?!-multilib)|\bgcc\b(?!-multilib)|\bclang(?:\+\+|-cl)?\b|\bcl\.exe\b"
    r"|\bdevenv(?:\.exe|\.com)?\s+\S+\.sln\b"
)


# The suffixes only one of the two languages uses.
C_SOURCES = {".c": "C"}
CXX_SOURCES = dict.fromkeys((".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ixx", ".cppm"), "C++")
# Headers (and included .inc files) do not tell C from C++: each is the language of the sources around it (see
# `facts.structure`). CMake modules belong to a C or C++ project only once it is recognised, as other ecosystems use
# some of these suffixes too, and the C++ template files to a C++ one.
SHARED_HEADERS = (".h", ".inc")
CXX_TEMPLATES = dict.fromkeys((".inl", ".ipp", ".tpp", ".txx"), "C++")


def c_family_ecosystem(
    language: str, sources: Mapping[str, str], ambiguous: Mapping[str, str] = MappingProxyType({})
) -> Ecosystem:
    """The ecosystem of C or C++ (`language`): its own `sources`, the shared headers, CMake modules, and any more
    `ambiguous` suffixes of its own."""
    return Ecosystem(
        label=language,
        languages=frozenset({language}),
        build_systems=(CMAKE, MESON),
        default_build_system=CMAKE,
        ci_programs=CI_PROGRAMS,
        ci_usage=CI_USAGE,
        source_suffixes=dict(sources),
        ambiguous_suffixes={**dict.fromkeys(SHARED_HEADERS, language), ".cmake": None, **ambiguous},
        family="C family",
    )


C = c_family_ecosystem("C", C_SOURCES)
