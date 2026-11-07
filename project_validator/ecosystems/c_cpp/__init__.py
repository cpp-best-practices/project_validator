"""C and C++: built with CMake or Meson, judged by their compilers.

Rules that depend on the build system are in the `cmake` and `meson` modules; a project with neither is judged as a
CMake project.
"""

import re
from typing import TYPE_CHECKING

from project_validator.ecosystems.c_cpp.cmake import CMAKE
from project_validator.ecosystems.c_cpp.compiler_flags import HARDENING, WARNINGS, WARNINGS_AS_ERRORS
from project_validator.ecosystems.c_cpp.meson import MESON
from project_validator.ecosystems.model import C_FAMILY, Ecosystem, ToolchainAxis
from project_validator.facts.outputs import BuildOutput
from project_validator.rules import (
    BuildTypes,
    directories,
    ignored_at_top_level,
)

if TYPE_CHECKING:
    from project_validator.ci import Job


# Building C or C++, as opposed to running another ecosystem's tools on a runner that has a C/C++ compiler.
CI_USAGE = re.compile(
    r"\b(?:cmake|ctest|meson|ninja|make|gmake|msbuild|devenv|bazel|conan|vcpkg|xmake|premake\d*|scons)\b"
    r"|\.(?:c|cc|cpp|cxx)\b|\bg\+\+|\bgcc\b|\bclang(?:\+\+|-cl)?\b|\bcl\.exe\b"
)


def _builds_c_or_cxx(job: Job) -> bool:
    """A job that names a compiler builds C/C++; one that only uses its runner's default compiler builds C/C++
    unless it is seen using another ecosystem's tools and not C/C++ build tools."""
    return not job.default_compiler or not job.ecosystems or "C/C++" in job.ecosystems


def _compilers(job: Job) -> frozenset[str]:
    return job.compilers if _builds_c_or_cxx(job) else frozenset()


def _uses_runner_default_compiler(job: Job) -> bool:
    return job.default_compiler and _builds_c_or_cxx(job)


COMPILERS = ToolchainAxis(noun="compiler", of_job=_compilers, runner_default=_uses_runner_default_compiler)


BUILD_DIRECTORY = BuildOutput(
    languages=C_FAMILY,
    name="the build directory",
    globs=ignored_at_top_level(r"(?:\[Bb\]uild|_?build|out|cmake-build)(?:[-_*][\w*-]*)?"),
    paths=directories("build", "out", "_build", "cmake-build-debug"),
    hint="consider ignoring the build directory (e.g. build/ and out/)",
    artifacts=(
        *("*.o", "*.obj", "*.a", "*.lib", "*.so", "*.so.*", "*.dylib", "*.dll", "*.exe", "*.pdb", "*.ilk"),
        *("CMakeCache.txt", "CMakeFiles/", "CMakeUserPresets.json", "cmake-build-*/"),
        *("/build/", "/out/", "/builddir/"),
    ),
)

# `.h` is deliberately absent: it is used by both C and C++.
C_AND_CXX = Ecosystem(
    label="C/C++",
    languages=C_FAMILY,
    build_systems=(CMAKE, MESON),
    default_build_system=CMAKE,
    ci_usage=CI_USAGE,
    source_suffixes={
        ".c": "C",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".hpp": "C++",
        ".hh": "C++",
        ".hxx": "C++",
        ".ixx": "C++",
        ".cppm": "C++",
    },
    # Headers (and included .inc files) do not tell C from C++, and CMake modules and C++ template files belong to
    # a C/C++ project only once it is recognised: other ecosystems use some of these suffixes too.
    ambiguous_suffixes={
        ".h": None,
        ".inc": None,
        ".cmake": None,
        ".inl": "C++",
        ".ipp": "C++",
        ".tpp": "C++",
        ".txx": "C++",
    },
    rules=(
        COMPILERS,
        BuildTypes(axis=COMPILERS),
        WARNINGS,
        WARNINGS_AS_ERRORS,
        HARDENING,
    ),
)
