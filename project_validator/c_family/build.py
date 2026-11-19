"""What C and C++ builds share: the compilers CI builds with (the platform matrix's toolchain axis) and the build
directory, which is never committed and always ignored."""

from __future__ import annotations

from project_validator.c_family.compiler_flags import builds_c_or_cxx
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts.axes import ToolchainAxis
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level


def _compilers(job: Job) -> frozenset[str]:
    return job.compilers if builds_c_or_cxx(job) else frozenset()


def _uses_runner_default_compiler(job: Job) -> bool:
    return job.default_compiler and builds_c_or_cxx(job)


COMPILERS = ToolchainAxis(
    languages=C_FAMILY, noun="compiler", of_job=_compilers, runner_default=_uses_runner_default_compiler, compiled=True
)


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
