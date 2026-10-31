import re
from collections.abc import Iterable

from project_validator.core import Context, Result, check
from project_validator.text import Pattern, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
CLANG_COMPILERS = frozenset({"clang", "appleclang"})


def _flag(name: str, regex: str) -> Pattern:
    """Flags must stand alone, so negated or disabled spellings (`-fcf-protection=none`, `/guard:cf-`) do not count."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=:-])"))


def _define(name: str, regex: str) -> Pattern:
    """A preprocessor definition, as `-DNAME=value` or `add_compile_definitions(NAME=value)`, but not `-UNAME`."""
    return Pattern(name, re.compile(rf"(?:-D\s*|(?<![\w-]))(?:{regex})(?![\w=])"))


FHARDENED = _flag("-fhardened", r"-fhardened")

GCC_CLANG_OPTIONS = (
    _define("_FORTIFY_SOURCE", r"_FORTIFY_SOURCE(?:=[1-9])?"),
    _flag("-fstack-protector-strong", r"-fstack-protector-(?:strong|all)"),
    _flag("-fcf-protection", r"-fcf-protection(?:=(?:full|branch|return|check))?"),
    _flag("-fstack-clash-protection", r"-fstack-clash-protection"),
    _define(
        "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE",
        r"_GLIBCXX_ASSERTIONS(?:=1)?|_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_(?:FAST|EXTENSIVE|DEBUG)",
    ),
)

MSVC_OPTIONS = (
    _flag("/sdl", r"/sdl"),
    _flag("/guard:cf", r"/guard:cf"),
    _flag("/DYNAMICBASE", r"(?i:/DYNAMICBASE)"),
    _flag("/CETCOMPAT", r"(?i:/CETCOMPAT)"),
)


def _found_and_missing(texts: tuple[str, ...], options: Iterable[Pattern]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for option in options:
        (found if any(option.regex.search(text) for text in texts) else missing).append(option.name)
    return found, missing


def _ci_compilers(context: Context) -> set[str]:
    return {compiler for job in context.ci_analysis.jobs for compiler in job.compilers}


def _preset_texts(context: Context) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in PRESET_FILES if context.project.exists(name))


def _names(options: Iterable[Pattern]) -> str:
    return ", ".join(option.name for option in options)


def _failure_message(msvc_required: bool) -> str:
    message = f"no hardening options found; enable -fhardened (GCC 14+) or {_names(GCC_CLANG_OPTIONS)}"
    return f"{message}, and for MSVC {_names(MSVC_OPTIONS)}" if msvc_required else message


@check(name="hardening", description="Security hardening options are enabled")
def hardening(context: Context) -> Result:
    compilers = _ci_compilers(context)
    msvc_required = "msvc" in compilers
    texts = (*context.cmake_texts, *context.ci_texts, *_preset_texts(context))

    if not matching_names(texts, (FHARDENED, *GCC_CLANG_OPTIONS, *MSVC_OPTIONS)):
        return Result.failed(_failure_message(msvc_required))

    fhardened = bool(matching_names(texts, (FHARDENED,)))
    found, missing = _found_and_missing(texts, GCC_CLANG_OPTIONS)
    msvc_found, msvc_missing = _found_and_missing(texts, MSVC_OPTIONS) if msvc_required else ([], [])
    enabled = ", ".join([*([FHARDENED.name] if fhardened else []), *found, *msvc_found])

    if fhardened and missing and compilers & CLANG_COMPILERS:
        return Result.warned(
            f"-fhardened is GCC-only; Clang in CI is missing hardening options: {', '.join([*missing, *msvc_missing])}",
            f"found {enabled}",
        )
    if missing := [*([] if fhardened else missing), *msvc_missing]:
        return Result.warned(f"missing hardening options: {', '.join(missing)}", f"found {enabled}")
    return Result.passed(f"hardening options are enabled: {enabled}")
