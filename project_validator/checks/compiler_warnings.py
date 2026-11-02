import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of
from project_validator.text import Pattern, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
PYTHON_SETTINGS_FILES = ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini")
CARGO_CONFIG_FILES = (".cargo/config.toml", ".cargo/config")
RUST_CRATE_ROOTS = frozenset({"Cargo.toml", "lib.rs", "main.rs"})


def _flag(name: str, regex: str) -> Pattern:
    """Compiler flags are case-sensitive and must stand alone (`-Wshadow`, not `-Wshadow=local`)."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=-])"))


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


GCC_CLANG_FLAGS = (
    _flag("-Wall", r"-Wall"),
    _flag("-Wextra", r"-Wextra"),
    _flag("-Wpedantic", r"-Wpedantic|-pedantic(?:-errors)?"),
    _flag("-Wshadow", r"-Wshadow"),
    _flag("-Wconversion", r"-Wconversion"),
)

MSVC_FLAGS = (
    _flag("/W4", r"/W4|/Wall"),
    Pattern("/permissive-", re.compile(r"(?<![\w/-])/permissive-(?![\w=-])")),
)

RUST_LINTS = (
    _setting("cargo clippy", r"\bcargo\s+(?:\+\S+\s+)?clippy\b"),
    _setting(
        "-D warnings",
        r"""-D[\s"',]*warnings\b|--deny[=\s]+warnings\b|\bdeny\s*\(\s*warnings\s*\)|^\s*warnings\s*=\s*["']deny["']""",
    ),
    _setting("clippy::pedantic", r"\bclippy::pedantic\b|^\s*pedantic\s*="),
)

# Python reports problems such as deprecations as warnings; the strict setting turns every one into an error.
PYTHON_WARNINGS = (
    _setting(
        "-W error",
        r"\bpython[\d.]*\s+(?:-\w+(?:\s+[^-\s]\S*)?\s+)*-W\s*error\b|\bpytest\b[^\n]*\s-W\s*error\b"
        r"|\bPYTHONWARNINGS\W+error\b|\bfilterwarnings\s*=\s*\[?\s*[\"']?error\b",
    ),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class WarningPolicy:
    """The warning settings an ecosystem must enable, every setting it recognises, and where they are found."""

    kind: str
    recognised: tuple[Pattern, ...]
    required: Callable[[Context], tuple[Pattern, ...]]
    texts: Callable[[Context], tuple[str, ...]]


def _found_and_missing(texts: tuple[str, ...], flags: Iterable[Pattern]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for flag in flags:
        (found if any(flag.regex.search(text) for text in texts) else missing).append(flag.name)
    return found, missing


def _existing_texts(context: Context, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in names if context.project.exists(name))


def _msvc_in_ci(context: Context) -> bool:
    return any("msvc" in job.compilers for job in context.ci_analysis.jobs)


def _c_and_cxx_required(context: Context) -> tuple[Pattern, ...]:
    return (*GCC_CLANG_FLAGS, *MSVC_FLAGS) if _msvc_in_ci(context) else GCC_CLANG_FLAGS


def _c_and_cxx_texts(context: Context) -> tuple[str, ...]:
    return (*context.cmake_texts, *context.ci_texts, *_existing_texts(context, PRESET_FILES))


def _rust_required(_: Context) -> tuple[Pattern, ...]:
    return RUST_LINTS


def _rust_texts(context: Context) -> tuple[str, ...]:
    crate_files = (path for path in context.project.files() if PurePosixPath(path).name in RUST_CRATE_ROOTS)
    return (*context.ci_texts, *_existing_texts(context, (*CARGO_CONFIG_FILES, *crate_files)))


def _python_required(_: Context) -> tuple[Pattern, ...]:
    return PYTHON_WARNINGS


def _python_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *_existing_texts(context, PYTHON_SETTINGS_FILES))


POLICIES = {
    C_AND_CXX: WarningPolicy(
        kind="compiler warning flags",
        recognised=(*GCC_CLANG_FLAGS, *MSVC_FLAGS),
        required=_c_and_cxx_required,
        texts=_c_and_cxx_texts,
    ),
    PYTHON: WarningPolicy(
        kind="Python warning settings", recognised=PYTHON_WARNINGS, required=_python_required, texts=_python_texts
    ),
    RUST: WarningPolicy(kind="Rust lint settings", recognised=RUST_LINTS, required=_rust_required, texts=_rust_texts),
}


def _enforced(policy: WarningPolicy, context: Context) -> Result:
    required = policy.required(context)
    texts = policy.texts(context)
    found, missing = _found_and_missing(texts, required)

    if not matching_names(texts, policy.recognised):
        return Result.failed(f"no {policy.kind} found; enable at least {' '.join(f.name for f in required)}")
    if missing:
        return Result.warned(f"missing {policy.kind}: {', '.join(missing)}", f"found {' '.join(found)}")
    return Result.passed(f"strict {policy.kind} are enabled: {' '.join(found)}")


@check(
    name="compiler-warnings",
    description="A strict compiler warning (or lint) set is enabled",
    languages=languages_of(POLICIES),
)
def compiler_warnings(context: Context) -> Result:
    return check_each_ecosystem(context, POLICIES, _enforced)
