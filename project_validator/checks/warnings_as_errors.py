import re

from project_validator.core import Context, Result, check
from project_validator.text import Pattern, matching_names

# Case-sensitive: compiler flags and CMake variable names are; `-Werror=<warning>`, `-Wno-error` and `/WX:NO` don't count.
WARNINGS_AS_ERRORS = (
    Pattern("-Werror", re.compile(r"(?<![\w=-])-Werror(?![\w=-])")),
    Pattern("/WX", re.compile(r"(?<![\w/:-])[/-]WX(?![\w:/-])")),
    Pattern(
        "COMPILE_WARNING_AS_ERROR",
        re.compile(
            r"(?:\b|(?<=-D))(?:CMAKE_)?COMPILE_WARNING_AS_ERROR\b(?::BOOL)?[\"']?\s*[=:\s]\s*[\"']?(?i:ON|TRUE|YES|Y|1)\b"
        ),
    ),
)


@check(name="warnings-as-errors", description="Compiler warnings are treated as errors in at least one configuration")
def warnings_as_errors(context: Context) -> Result:
    if flags := matching_names((*context.ci_texts, *context.cmake_texts), WARNINGS_AS_ERRORS):
        return Result.passed(f"warnings are treated as errors with {', '.join(flags)}")
    return Result.failed(
        "warnings are not treated as errors in CI configuration or CMake files",
        "add -Werror (GCC/Clang), /WX (MSVC) or set CMAKE_COMPILE_WARNING_AS_ERROR, at least as an option",
    )
