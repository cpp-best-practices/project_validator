"""clang-tidy and cppcheck: the C and C++ static analyzers, which find different bugs, so both must run.

Each runs directly, through a launcher or action, or within the build: a CMake configuration that sets
`CMAKE_<LANG>_CLANG_TIDY` or `CMAKE_<LANG>_CPPCHECK` (or the target property) runs it on every file it compiles.
"""

import re

from project_validator.build_systems.cmake.build import cmake_configures
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.build import BuildSetting
from project_validator.facts.expansion import Action
from project_validator.facts.tools import Claim, Run, defined_by
from project_validator.tools.scanners import multi_language_scanners

# A CMake variable (or target property) that runs an analyzer on every file the build compiles.
_ANALYZER_SETTING = re.compile(r"(?:CMAKE_)?(?:C|CXX|OBJC|OBJCXX)_(CLANG_TIDY|CPPCHECK)")


def _analyzer_settings(facts: Facts, variable: str) -> list[str]:
    """The files of the CMake settings (variables, target properties, presets) that run the analyzer `variable`."""
    found = (setting for setting in facts.of(BuildSetting) if setting.value and setting.build_system == "CMake")
    return [
        setting.origin.path
        for setting in found
        if (match := _ANALYZER_SETTING.fullmatch(setting.name)) and match[1] == variable
    ]


def _analyzer(programs: re.Pattern[str], variable: str) -> Claim:
    """A run of the analyzer `programs` name, or of a CMake configuration whose build runs it (`variable` set on its
    command line, or in the CMake files and presets)."""

    def analyses(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if programs.fullmatch(program(argv)):
            return analysed()
        if not cmake_configures(argv):
            return None
        if any(re.match(rf"-DCMAKE_\w+_{variable}(?::\w+)?=.", word) for word in argv):
            return analysed()
        read = _analyzer_settings(facts, variable)
        return analysed(read=read) if read else None

    return analyses


CLANG_TIDY = analyzer(
    name="clang-tidy",
    languages=C_FAMILY,
    how="clang-tidy (CMAKE_CXX_CLANG_TIDY, checks chosen in a .clang-tidy)",
    analyses=_analyzer(re.compile(r"(?:run-)?clang-tidy(?:-\d+)?(?:\.py)?"), "CLANG_TIDY"),
    rules=defined_by(files=("clang-tidy",), default=False),
    reads=("CMake",),
    required=True,
)
CPPCHECK = analyzer(
    name="cppcheck",
    languages=C_FAMILY,
    how="cppcheck (CMAKE_CXX_CPPCHECK)",
    analyses=_analyzer(re.compile(r"cppcheck(?:-htmlreport)?"), "CPPCHECK"),
    reads=("CMake",),
    required=True,
)


def _runs_clang_tidy(inputs: object) -> tuple[tuple[str, ...], ...]:
    return (("clang-tidy",),)


# cpp-linter runs clang-tidy and clang-format (with the project's .clang-tidy); clang-tidy-review runs clang-tidy.
CPP_LINTER_ACTION = Action(name="cpp-linter/cpp-linter-action", runs=_runs_clang_tidy)
CLANG_TIDY_REVIEW_ACTION = Action(name="ZedThree/clang-tidy-review", runs=_runs_clang_tidy)
CPPCHECK_ACTION = Action(name="deep5050/cppcheck-action", runs=lambda _inputs: (("cppcheck",),))

# C and C++ have no security lints of their own here: CodeQL, GitLab SAST or semgrep scan them.
SECURITY_SCANNERS = multi_language_scanners(C_FAMILY)
