"""clang-tidy and cppcheck: the C and C++ static analyzers, which find different bugs, so both must run.

Each runs directly, through a launcher or action, or within the build: a CMake configuration that sets
`CMAKE_<LANG>_CLANG_TIDY` or `CMAKE_<LANG>_CPPCHECK` runs it on every file it compiles. Those variables are matched
in the CMake files and presets until CMake is read structurally.
"""

import re
from collections.abc import Iterable

from project_validator.ecosystems.c_cpp.coverage import cmake_configures
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Command, Fact, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.expansion import Action
from project_validator.facts.settings import SettingsReader, matched_settings
from project_validator.facts.tools import Claim, Run, defined_by
from project_validator.text import strip_cmake_comments
from project_validator.tools.scanners import multi_language_scanners

# A CMake variable that runs an analyzer on every file the build compiles, as CMake files and presets set it.
_ANALYZER_VARIABLE = re.compile(r"\bCMAKE_(?:C|CXX|OBJC|OBJCXX)_(CLANG_TIDY|CPPCHECK)\b")


def _read_cmake_analyzers(path: str, text: str) -> Iterable[Fact]:
    found = strip_cmake_comments(text) if not path.endswith(".json") else text
    return matched_settings("CMake", path, found, {"analyzer": (_ANALYZER_VARIABLE, None)})


CMAKE_ANALYZERS = SettingsReader(
    name="CMake analyzers",
    files=("CMakeLists.txt", "*.cmake", "CMakePresets.json", "CMakeUserPresets.json"),
    read=_read_cmake_analyzers,
)


def _analyzer(programs: re.Pattern[str], variable: str) -> Claim:
    """A run of the analyzer `programs` name, or of a CMake configuration whose build runs it (`variable` set on its
    command line, or in the CMake files and presets: heuristic)."""

    def analyses(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if programs.fullmatch(program(argv)):
            return analysed()
        if not cmake_configures(argv):
            return None
        if any(re.match(rf"-DCMAKE_\w+_{variable}(?::\w+)?=.", word) for word in argv):
            return analysed()
        read = facts.where(Setting, tool="CMake", key="analyzer", value=variable)
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
