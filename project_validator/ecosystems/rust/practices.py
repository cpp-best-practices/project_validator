"""Rust's practices: the settings it asks for, and how they are worded (see
`project_validator.facts.practices`)."""

import re

from project_validator.ecosystems.rust import RUST_LANGUAGE
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.text import Pattern

CARGO_CONFIG_FILES = (".cargo/config.toml", ".cargo/config")


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


RUST_LINTS = (
    _setting("cargo clippy", r"\bcargo\s+(?:\+\S+\s+)?clippy\b"),
    _setting(
        "-D warnings",
        r"""-D[\s"',]*warnings\b|--deny[=\s]+warnings\b|\bdeny\s*\(\s*warnings\s*\)|^\s*warnings\s*=\s*["']deny["']""",
    ),
    _setting("clippy::pedantic", r"\bclippy::pedantic\b|^\s*pedantic\s*="),
)


RUST_LINT_SETTINGS_FILES = (*CARGO_CONFIG_FILES, "Cargo.toml", "lib.rs", "main.rs")


_RUST_LINTS = tuple(required(lint) for lint in RUST_LINTS)


RUST_WARNING_SETTINGS = requirement_reader("Rust lint settings", RUST_LINT_SETTINGS_FILES, _RUST_LINTS)


WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=RUST_LANGUAGE,
    requirements=always(*_RUST_LINTS),
    reads=(RUST_WARNING_SETTINGS.name,),
    words=Wording(
        kind="Rust lint settings",
        separator=" ",
        hint='run cargo clippy, deny warnings (-D warnings or [lints.rust] warnings = "deny") and enable '
        "clippy::pedantic",
    ),
)


# Overflow checks are compiled into the binary; release builds leave them out unless the profile asks for them.
_OVERFLOW_CHECKS = required(
    _setting(
        "release overflow-checks",
        r"^\[profile\.release\][^\[]*^\s*overflow-checks\s*=\s*true\b"
        r"""|-C[\s"',]*overflow-checks(?:=(?:on|yes|y|true))?(?![\w=-])""",
    )
)


RUST_HARDENING_SETTINGS = requirement_reader("Rust build settings", RUST_LINT_SETTINGS_FILES, (_OVERFLOW_CHECKS,))


HARDENING = Practice(
    name=PracticeName.HARDENING,
    languages=RUST_LANGUAGE,
    requirements=always(_OVERFLOW_CHECKS),
    reads=(RUST_HARDENING_SETTINGS.name,),
    words=Wording(
        kind="hardening options",
        hint="set overflow-checks = true in [profile.release] of Cargo.toml",
    ),
)
