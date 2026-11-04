import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, Ecosystem, check_each_ecosystem, languages_of
from project_validator.text import Pattern, found_and_missing, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
PYTHON_SETTINGS_FILES = ("pyproject.toml", "setup.cfg", "tox.ini", "ruff.toml", ".ruff.toml", ".pre-commit-config.yaml")
CARGO_CONFIG_FILES = (".cargo/config.toml", ".cargo/config")
RUST_SETTINGS_FILES = frozenset({"Cargo.toml", "lib.rs", "main.rs"})
CLANG_COMPILERS = frozenset({"clang", "appleclang"})


def _flag(name: str, regex: str) -> Pattern:
    """Flags must stand alone, so negated or disabled spellings (`-fcf-protection=none`, `/guard:cf-`) do not count."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=:-])"))


def _define(name: str, regex: str) -> Pattern:
    """A preprocessor definition, as `-DNAME=value` or `add_compile_definitions(NAME=value)`, but not `-UNAME`."""
    return Pattern(name, re.compile(rf"(?:-D\s*|(?<![\w-]))(?:{regex})(?![\w=])"))


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


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

# Python has no compiler mitigations; its hardening is linting for insecure code and refusing tampered dependencies.
PYTHON_OPTIONS = (
    _setting(
        "bandit security lints",
        r"\bbandit\s+-|\bid:\s*bandit\b|\bPyCQA/bandit-action\b"
        r"""|\bruff\b[^\n]*--(?:extend-)?select[=\s]+(?:\S*,)?(?:S\d*|ALL)(?![\w-])"""
        r"""|\b(?:extend-)?select\s*=\s*\[[^\]]*["'](?:S\d*|ALL)["']""",
    ),
    _setting(
        "hash-checked dependencies",
        r"--require-hashes\b|--generate-hashes\b|\buv\s+sync\b[^\n]*--(?:locked|frozen)\b",
    ),
)

RUST_OPTIONS = (
    _setting(
        "unsafe_code forbidden",
        r"#!\[\s*(?:forbid|deny)\s*\([^)]*\bunsafe_code\b"
        r"""|^\s*unsafe_code\s*=\s*(?:\{[^}]*\blevel\s*=\s*)?["'](?:forbid|deny)["']"""
        r"""|-[FD][\s"',]*unsafe_code\b|--(?:forbid|deny)[=\s]+unsafe_code\b""",
    ),
    _setting(
        "release overflow-checks",
        r"^\[profile\.release\][^\[]*^\s*overflow-checks\s*=\s*true\b"
        r"""|-C[\s"',]*overflow-checks(?:=(?:on|yes|y|true))?(?![\w=-])""",
    ),
)


def _existing_texts(context: Context, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in names if context.project.exists(name))


def _ci_compilers(context: Context) -> set[str]:
    return {compiler for job in context.ci_analysis.jobs for compiler in job.compilers}


def _names(options: Iterable[Pattern]) -> str:
    return ", ".join(option.name for option in options)


def _c_and_cxx_failure(msvc_required: bool) -> str:
    message = f"no hardening options found; enable -fhardened (GCC 14+) or {_names(GCC_CLANG_OPTIONS)}"
    return f"{message}, and for MSVC {_names(MSVC_OPTIONS)}" if msvc_required else message


def _c_and_cxx_hardening(context: Context) -> Result:
    compilers = _ci_compilers(context)
    msvc_required = "msvc" in compilers
    texts = (*context.cmake_texts, *context.ci_texts, *_existing_texts(context, PRESET_FILES))

    if not matching_names(texts, (FHARDENED, *GCC_CLANG_OPTIONS, *MSVC_OPTIONS)):
        return Result.failed(_c_and_cxx_failure(msvc_required))

    fhardened = bool(matching_names(texts, (FHARDENED,)))
    found, missing = found_and_missing(texts, GCC_CLANG_OPTIONS)
    msvc_found, msvc_missing = found_and_missing(texts, MSVC_OPTIONS) if msvc_required else ([], [])
    enabled = ", ".join([*([FHARDENED.name] if fhardened else []), *found, *msvc_found])

    if fhardened and missing and compilers & CLANG_COMPILERS:
        return Result.warned(
            f"-fhardened is GCC-only; Clang in CI is missing hardening options: {', '.join([*missing, *msvc_missing])}",
            f"found {enabled}",
        )
    if missing := [*([] if fhardened else missing), *msvc_missing]:
        return Result.warned(f"missing hardening options: {', '.join(missing)}", f"found {enabled}")
    return Result.passed(f"hardening options are enabled: {enabled}")


def _required_options(texts: tuple[str, ...], options: tuple[Pattern, ...]) -> Result:
    found, missing = found_and_missing(texts, options)
    if not found:
        return Result.failed(f"no hardening options found; enable {_names(options)}")
    if missing:
        return Result.warned(f"missing hardening options: {', '.join(missing)}", f"found {', '.join(found)}")
    return Result.passed(f"hardening options are enabled: {', '.join(found)}")


def _python_hardening(context: Context) -> Result:
    texts = (*context.ci_texts, *_existing_texts(context, PYTHON_SETTINGS_FILES))
    return _required_options(texts, PYTHON_OPTIONS)


def _rust_hardening(context: Context) -> Result:
    settings = (path for path in context.project.files() if PurePosixPath(path).name in RUST_SETTINGS_FILES)
    texts = (*context.ci_texts, *_existing_texts(context, (*CARGO_CONFIG_FILES, *settings)))
    return _required_options(texts, RUST_OPTIONS)


JUDGES: dict[Ecosystem, Callable[[Context], Result]] = {
    C_AND_CXX: _c_and_cxx_hardening,
    PYTHON: _python_hardening,
    RUST: _rust_hardening,
}


def _judged(judge: Callable[[Context], Result], context: Context) -> Result:
    return judge(context)


@check(name="hardening", description="Security hardening options are enabled", languages=languages_of(JUDGES))
def hardening(context: Context) -> Result:
    return check_each_ecosystem(context, JUDGES, _judged)
