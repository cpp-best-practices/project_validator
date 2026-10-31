"""Recognising operating systems and compilers in CI configuration text."""

from project_validator.text import matching_names, pattern

OPERATING_SYSTEMS = (
    pattern("linux", r"\b(ubuntu|linux|debian|fedora|alpine|centos|rocky|archlinux)\b"),
    pattern("windows", r"\b(windows|win32|win64|vs20\d\d)\b|visual studio"),
    pattern("macos", r"\b(macos|osx|mac-os)\b"),
)

COMPILERS = (
    pattern("gcc", r"\bgcc\b|\bg\+\+|\bmingw"),
    pattern("clang", r"\bclang(?![-_]?(tidy|format|d|-apply-replacements)\b)"),
    pattern("appleclang", r"\bapple-?clang\b"),
    pattern("msvc", r"\bmsvc|visual studio|\bvs20\d\d\b|\bcl\.exe\b|\bvcvars"),
    pattern("intel", r"\bicp?x\b|\bicp?c\b|intel-oneapi"),
)

RUNNER_DEFAULT_COMPILERS = {"linux": "gcc", "macos": "appleclang", "windows": "msvc"}


def detect_operating_systems(text: str) -> list[str]:
    return matching_names((text,), OPERATING_SYSTEMS)


def detect_compilers(text: str) -> list[str]:
    return matching_names((text,), COMPILERS)
