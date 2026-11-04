"""CMake: C/C++ rules that depend on CMake files, such as CTest registration and CMAKE_<LANG>_EXTENSIONS."""

import re
from collections.abc import Iterable
from pathlib import Path

from project_validator.core import Context, Result
from project_validator.ecosystems.c_cpp.compiler_flags import PRESET_FILES
from project_validator.ecosystems.c_cpp.ctest import CTEST
from project_validator.ecosystems.model import C_FAMILY, BuildSystem
from project_validator.evidence import existing_texts
from project_validator.rules import CompilerExtensions
from project_validator.text import Pattern, matching_names, pattern

_DISABLED = r'"?(?:OFF|FALSE|NO|N|0)\b"?'
_LANGUAGE_DECLARATIONS = re.compile(r"\b(?:project|enable_language)\s*\(([^)]*)\)", re.IGNORECASE)
_LANGUAGE_NAMES = {"CXX": "C++", "C": "C"}


def global_settings(language: str) -> tuple[Pattern, ...]:
    variable = f"CMAKE_{language}_EXTENSIONS"
    return (
        pattern(f"set({variable} OFF)", rf"\bset\s*\(\s*{variable}\s+{_DISABLED}"),
        pattern(f"-D{variable}=OFF", rf"-D\s*{variable}(?::\w+)?={_DISABLED}"),
        pattern("CMakePresets.json", rf'"{variable}"\s*:\s*(?:\{{[^}}]*"value"\s*:\s*)?{_DISABLED}'),
    )


def target_settings(language: str) -> tuple[Pattern, ...]:
    return (pattern(f"{language}_EXTENSIONS OFF", rf"\b{language}_EXTENSIONS\s+{_DISABLED}"),)


def declared_languages(cmake_texts: Iterable[str]) -> set[str]:
    return {
        word.upper()
        for text in cmake_texts
        for declaration in _LANGUAGE_DECLARATIONS.finditer(text)
        for word in declaration[1].split()
    }


def checked_language(cmake_texts: Iterable[str]) -> str:
    languages = declared_languages(cmake_texts)
    return "C" if "C" in languages and "CXX" not in languages else "CXX"


def _preset_texts(context: Context) -> tuple[str, ...]:
    return existing_texts(context, PRESET_FILES)


def _extensions_disabled(context: Context) -> Result:
    language = checked_language(context.cmake_texts)
    label = _LANGUAGE_NAMES[language]
    global_fix = f"set(CMAKE_{language}_EXTENSIONS OFF)"

    global_texts = (*context.cmake_texts, *context.ci_texts, *_preset_texts(context))
    if found := matching_names(global_texts, global_settings(language)):
        return Result.passed(f"{label} compiler extensions are disabled globally with {', '.join(found)}")
    if found := matching_names(context.cmake_texts, target_settings(language)):
        return Result.passed(
            f"{label} compiler extensions are disabled per target with {', '.join(found)}",
            f"consider {global_fix} so that every target has extensions disabled",
        )
    return Result.failed(f"{label} compiler extensions are never disabled; add {global_fix}")


def is_cmake_build_tree(directory: Path) -> bool:
    return (directory / "CMakeCache.txt").is_file()


CMAKE = BuildSystem(
    name="CMake",
    files=("CMakeLists.txt",),
    languages=C_FAMILY,
    is_build_tree=is_cmake_build_tree,
    rules=(CTEST, CompilerExtensions(judge=_extensions_disabled)),
)
