import re
from collections.abc import Iterable

from project_validator.core import Context, Result, check
from project_validator.structure import C_FAMILY
from project_validator.text import Pattern, matching_names, pattern

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")

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
    return tuple(context.project.read_text(name) for name in PRESET_FILES if context.project.exists(name))


@check(
    name="cxx-extensions",
    description="Compiler extensions are disabled (-std=c++NN rather than -std=gnu++NN)",
    languages=C_FAMILY,
)
def cxx_extensions(context: Context) -> Result:
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
