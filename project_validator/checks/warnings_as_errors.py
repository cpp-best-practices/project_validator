import re

from project_validator.core import Context, Result, check
from project_validator.structure import C_FAMILY
from project_validator.text import Pattern, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")

# Case-sensitive, as compiler flags and CMake variable names are.
# Partial or disabling forms such as `-Werror=<warning>`, `-Wno-error` and `/WX:NO` don't count.
WARNINGS_AS_ERRORS = (
    Pattern("-Werror", re.compile(r"(?<![\w=-])-Werror(?![\w=-])")),
    Pattern("/WX", re.compile(r"(?<![\w/:-])[/-]WX(?![\w:/-])")),
    Pattern(
        "COMPILE_WARNING_AS_ERROR",
        re.compile(
            r"(?:\b|(?<=-D))(?:CMAKE_)?COMPILE_WARNING_AS_ERROR\b(?::BOOL)?[\"']?\s*[=:\s]\s*"
            r"(?:\{[^}]*\"value\"\s*:\s*)?[\"']?(?i:ON|TRUE|YES|Y|1)\b"
        ),
    ),
)


def _preset_texts(context: Context) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in PRESET_FILES if context.project.exists(name))


@check(
    name="warnings-as-errors",
    description="Compiler warnings are treated as errors in at least one configuration",
    languages=C_FAMILY,
)
def warnings_as_errors(context: Context) -> Result:
    texts = (*context.ci_texts, *context.cmake_texts, *_preset_texts(context))
    if flags := matching_names(texts, WARNINGS_AS_ERRORS):
        return Result.passed(f"warnings are treated as errors with {', '.join(flags)}")
    return Result.failed(
        "warnings are not treated as errors in CI configuration, CMake files or presets",
        "add -Werror (GCC/Clang), /WX (MSVC) or set CMAKE_COMPILE_WARNING_AS_ERROR, at least as an option",
    )
