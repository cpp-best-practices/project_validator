"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import re
import shlex
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, toml_members, versions_axis
from project_validator.evidence import existing_texts, toml_value
from project_validator.facts import Command, Fact, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action
from project_validator.facts.expansion import Action as AuditAction
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, matched_settings, settings, toml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either, starts, when
from project_validator.rules import (
    BuildOutputs,
    BuildTypes,
    DependencyManagement,
    FunctionLimits,
    Hardening,
    WarningPolicy,
    directories,
    ignored_at_top_level,
    toml_license,
)
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.scanners import multi_language_scanners


def is_cargo_target(directory: Path) -> bool:
    """Cargo tags its output with CACHEDIR.TAG and, by default, puts it in `target/` beside `Cargo.toml`."""
    return (directory / "CACHEDIR.TAG").is_file() or (
        directory.name == "target" and (directory.parent / "Cargo.toml").is_file()
    )


_CARGO_BUILDS = (("build",), ("test",), ("run",), ("nextest", "run"))


def cargo_build_types(command: Command) -> frozenset[str]:
    """The profile `cargo build`, `test`, `run` or `nextest run` builds: release with `--release` or
    `--profile release`, debug without either, and neither with another profile."""
    argv = [word for word in resolved(command) if not word.startswith("+")]
    if argv[:1] != ["cargo"] or not any(tuple(argv[1 : 1 + len(sub)]) == sub for sub in _CARGO_BUILDS):
        return frozenset()
    profiles = option_values(tuple(argv), "--profile")
    if "--release" in argv or "release" in profiles:
        return frozenset({"release"})
    return frozenset() if profiles else frozenset({"debug"})


RUST_LANGUAGE = frozenset({"Rust"})
CARGO = BuildSystem(
    name="Cargo",
    files=("Cargo.toml",),
    languages=RUST_LANGUAGE,
    is_build_tree=is_cargo_target,
    build_types=cargo_build_types,
    members=toml_members("workspace"),
)

_RUST_VERSION = r"(stable|beta|nightly|\d+\.\d+(?:\.\d+)?)"

RUST_TOOLCHAINS = versions_axis("Rust toolchain", "Rust")


RUSTFMT_SETTINGS = SettingsReader(
    name="rustfmt",
    files=("rustfmt.toml", ".rustfmt.toml"),
    read=lambda path, text: toml_settings("rustfmt", path, text),
)


def _cargo_fmt(command: Command, facts: Facts) -> Run | None:
    """`cargo fmt --check` (`cargo +nightly fmt --all -- --check`) checks; `cargo fmt` applies."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    if program(argv) != "cargo" or argv[1:2] != ("fmt",):
        return None
    return formatted(command, facts, checks="--check" in argv)


RUSTFMT = format_tool(
    name="rustfmt",
    languages=RUST_LANGUAGE,
    can={Enforcement.CHECK: "cargo fmt --check", Enforcement.APPLY: "cargo fmt"},
    formats=either(_cargo_fmt, flagged(("rustfmt",), checks=("--check",))),
    style=defined_by(files=("rustfmt",)),
    reads=("rustfmt",),
)
RUSTFMT_ACTION = Action(name="actions-rust-lang/rustfmt", runs=lambda _inputs: (("cargo", "fmt", "--check"),))


def _cargo(command: Command, name: str) -> tuple[str, ...] | None:
    """The arguments after `cargo [+toolchain] name`, when the command runs that cargo subcommand."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    return argv[1:] if argv[:2] == ("cargo", name) else None


def _cargo_llvm_cov(command: Command, _: Facts) -> Run | None:
    if (argv := _cargo(command, "llvm-cov")) is None:
        return None
    branch = has_option(argv, "--branch")
    return measured(LINE, REGION, BRANCH if branch else None, PATH if has_option(argv, "--mcdc") else None)


def _cargo_tarpaulin(command: Command, _: Facts) -> Run | None:
    if (argv := _cargo(command, "tarpaulin")) is None:
        return None
    return measured(LINE, BRANCH if has_option(argv, "--branch", "-b") else None)


def _grcov(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) != "grcov":
        return None
    return measured(LINE, BRANCH if has_option(argv, "--branch") else None)


_MCDC = re.compile(r"-Z\s*coverage-options=\S*mcdc")


def _rustc_mcdc(command: Command, _: Facts) -> Run | None:
    """rustc's MC/DC instrumentation, on a command line or in RUSTFLAGS."""
    words = (" ".join(resolved(command)), command.env.get("RUSTFLAGS", ""))
    return measured(PATH) if any(_MCDC.search(word) for word in words) else None


LINE, REGION, BRANCH, PATH = Granularity.LINE, Granularity.REGION, Granularity.BRANCH, Granularity.PATH
CARGO_LLVM_COV = coverage_tool(
    name="cargo-llvm-cov",
    languages=RUST_LANGUAGE,
    can={
        LINE: "cargo llvm-cov",
        REGION: "cargo llvm-cov",
        BRANCH: "cargo llvm-cov --branch",
        PATH: "cargo llvm-cov --mcdc",
    },
    measures=_cargo_llvm_cov,
)
CARGO_TARPAULIN = coverage_tool(
    name="cargo-tarpaulin",
    languages=RUST_LANGUAGE,
    can={LINE: "cargo tarpaulin", BRANCH: "cargo tarpaulin --branch"},
    measures=_cargo_tarpaulin,
)
GRCOV = coverage_tool(
    name="grcov", languages=RUST_LANGUAGE, can={LINE: "grcov", BRANCH: "grcov --branch"}, measures=_grcov
)
RUSTC_MCDC = coverage_tool(
    name="rustc MC/DC",
    languages=RUST_LANGUAGE,
    can={PATH: "RUSTFLAGS=-Zcoverage-options=mcdc"},
    measures=_rustc_mcdc,
)

RUST_TEST_FILES = TestFiles(
    name="#[test] functions",
    languages=RUST_LANGUAGE,
    path=re.compile(r"\.rs$"),
    contains=re.compile(r"#\[(?:\w+::)*test\b"),
)


def _cargo_test(command: Command, _facts: Facts) -> Run | None:
    """`cargo test`, and the cargo tools that run the tests: nextest, llvm-cov and tarpaulin (any toolchain)."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    runs = program(argv) == "cargo" and argv[1:2] in (("test",), ("nextest",), ("llvm-cov",), ("tarpaulin",))
    return tested() if runs else None


CARGO_TEST = test_runner(
    name="cargo test", languages=RUST_LANGUAGE, how="cargo test", runs=_cargo_test, tests=tests_of(RUST_TEST_FILES.name)
)


CARGO_CONFIG_FILES = (".cargo/config.toml", ".cargo/config")
CRATE_SETTINGS_FILES = frozenset({"Cargo.toml", "lib.rs", "main.rs"})


def _settings_texts(context: Context) -> tuple[str, ...]:
    """Where Rust lints and profiles are set: CI configuration, Cargo configuration, manifests and crate roots."""
    crate_files = (path for path in context.project.files() if PurePosixPath(path).name in CRATE_SETTINGS_FILES)
    return (*context.ci_texts, *existing_texts(context, (*CARGO_CONFIG_FILES, *crate_files)))


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


def _required_lints(_: Context) -> tuple[Pattern, ...]:
    return RUST_LINTS


WARNINGS = WarningPolicy(
    kind="Rust lint settings", recognised=RUST_LINTS, required=_required_lints, texts=_settings_texts
)

# Overflow checks are compiled into the binary; release builds leave them out unless the profile asks for them.
HARDENING = Hardening(
    texts=_settings_texts,
    options=(
        _setting(
            "release overflow-checks",
            r"^\[profile\.release\][^\[]*^\s*overflow-checks\s*=\s*true\b"
            r"""|-C[\s"',]*overflow-checks(?:=(?:on|yes|y|true))?(?![\w=-])""",
        ),
    ),
)

# Forbidding unsafe code crate-wide makes the compiler reject the code whose memory safety it cannot check: in the
# manifest's lints table, as a crate attribute, or on the command line.
_FORBIDS_UNSAFE = re.compile(r"#!\[\s*(?:forbid|deny)\s*\([^)]*\bunsafe_code\b")
_UNSAFE_FLAG = re.compile(r"""-[FD][\s"',]*unsafe_code\b|--(?:forbid|deny)[=\s]+unsafe_code\b""")
_FORBIDDEN = frozenset({"forbid", "deny"})


def _flags(value: object) -> str:
    return " ".join(map(str, value if isinstance(value, tuple) else (value,)))


def _cargo_configuration(path: str, text: str) -> Iterator[Fact]:
    """The rustflags of Cargo's configuration, when they forbid unsafe code."""
    for fact in toml_settings("Rust lints", path, text, "build"):
        if not isinstance(fact, Setting):
            yield fact
        elif fact.key == "rustflags" and _UNSAFE_FLAG.search(_flags(fact.value)):
            yield from settings("Rust lints", path, (("unsafe_code", "forbid"),))


def _read_unsafe_code(path: str, text: str) -> Iterator[Fact]:
    """Unsafe code forbidden: in a manifest's lints, a crate attribute, or the rustflags of Cargo's configuration."""
    if PurePosixPath(path).parent.name == ".cargo":
        yield from _cargo_configuration(path, text)
    elif PurePosixPath(path).name == "Cargo.toml":
        for table in (("lints", "rust"), ("workspace", "lints", "rust")):
            found = toml_settings("Rust lints", path, text, *table)
            yield from (fact for fact in found if not isinstance(fact, Setting) or fact.key.startswith("unsafe_code"))
    else:
        yield from matched_settings("Rust lints", path, text, {"unsafe_code": (_FORBIDS_UNSAFE, "forbid")})


RUST_LINT_SETTINGS = SettingsReader(
    name="Rust lints",
    files=("Cargo.toml", "lib.rs", "main.rs", ".cargo/config.toml", ".cargo/config"),
    read=_read_unsafe_code,
)
_CARGO_COMPILES = frozenset({"build", "check", "test", "clippy", "run", "rustc", "nextest", "llvm-cov", "tarpaulin"})


def _unsafe_forbidden(command: Command, facts: Facts) -> Run | None:
    """A cargo build that compiles the crate with unsafe code forbidden, by its settings or flags."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    if program(argv) != "cargo" or not argv[1:2] or argv[1] not in _CARGO_COMPILES:
        return None
    if _UNSAFE_FLAG.search(" ".join((*argv, command.env.get("RUSTFLAGS", "")))):
        return scanned()
    read = [setting for setting in facts.settings("Rust lints") if str(setting.value) in _FORBIDDEN]
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(
        name="unsafe_code forbidden",
        languages=RUST_LANGUAGE,
        how='unsafe_code = "forbid" in [lints.rust]',
        scans=_unsafe_forbidden,
        reads=("Rust lints",),
    ),
    *multi_language_scanners(RUST_LANGUAGE),
)

_DENY_CHECKS = frozenset({"advisories", "bans", "licenses", "sources"})


def _cargo_deny(command: Command, _facts: Facts) -> Run | None:
    """`cargo deny check`, which checks advisories unless told to run only its other checks."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    if not (argv[:2] == ("cargo", "deny") or program(argv) == "cargo-deny") or "check" not in argv:
        return None
    checks = [word for word in argv[argv.index("check") + 1 :] if word in _DENY_CHECKS]
    return audited() if not checks or "advisories" in checks else None


AUDITORS = (
    auditor(
        name="cargo audit",
        languages=RUST_LANGUAGE,
        how="cargo audit",
        audits=when(starts(("cargo", "audit"), ("cargo-audit",)), audited),
    ),
    auditor(name="cargo deny", languages=RUST_LANGUAGE, how="cargo deny check advisories", audits=_cargo_deny),
    *multi_ecosystem_audits(RUST_LANGUAGE),
)
CARGO_AUDIT_ACTIONS = tuple(
    AuditAction(name=name, runs=lambda _inputs: (("cargo", "audit"),))
    for name in ("rustsec/audit-check", "actions-rust-lang/audit")
)
CARGO_DENY_ACTION = AuditAction(
    name="EmbarkStudios/cargo-deny-action",
    runs=lambda inputs: (
        ("cargo", "deny", *shlex.split(inputs.get("arguments", "")), *shlex.split(inputs.get("command", "check"))),
    ),
)

TARGET_DIRECTORY = BuildOutputs(
    name="the target directory",
    globs=ignored_at_top_level("target"),
    paths=directories("target"),
    hint="consider ignoring /target",
    artifacts=("/target/",),
)

LICENSE = toml_license("Cargo.toml", "package")

DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")
BINARY_SOURCES = re.compile(r"(?:^|/)src/(?:main\.rs|bin/[^/]+)$")


def _declares_dependencies(context: Context) -> str | None:
    """Cargo manages the dependencies a crate (or its workspace) declares in Cargo.toml."""
    tables = [toml_value(context, "Cargo.toml", table) for table in DEPENDENCY_TABLES]
    tables.append(toml_value(context, "Cargo.toml", "workspace", "dependencies"))
    return "managed with Cargo" if any(tables) else None


def _builds_a_binary(context: Context) -> bool:
    """A binary's builds should be reproducible, so it commits Cargo.lock; a library's users resolve their own."""
    has_bin_table = context.project.exists("Cargo.toml") and "[[bin]]" in context.project.read_text("Cargo.toml")
    return has_bin_table or any(BINARY_SOURCES.search(path) for path in context.tracked_files)


def _cargo_lock(context: Context) -> str | None:
    return "Cargo.lock" if context.committed("Cargo.lock") else None


DEPENDENCIES = DependencyManagement(
    managed=_declares_dependencies,
    locked=_cargo_lock,
    lock_required=_builds_a_binary,
    lock_hint="commit Cargo.lock, so the binary is always built with the dependencies it was tested with",
)


def _read_lints(path: str, text: str) -> Iterator[Fact]:
    """clippy's settings: clippy.toml, or the `[lints.clippy]` (or `[workspace.lints.clippy]`) table of Cargo.toml."""
    if PurePosixPath(path).name != "Cargo.toml":
        return toml_settings("clippy", path, text)
    return (
        fact
        for table in (("lints", "clippy"), ("workspace", "lints", "clippy"))
        for fact in toml_settings("clippy", path, text, *table)
    )


CLIPPY_SETTINGS = SettingsReader(name="clippy", files=("clippy.toml", ".clippy.toml", "Cargo.toml"), read=_read_lints)


def _clippy(command: Command, _facts: Facts) -> Run | None:
    """`cargo clippy`, with any toolchain (`cargo +nightly clippy`)."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    return analysed() if program(argv) in ("cargo", "cargo-clippy") and "clippy" in argv[:2] else None


CLIPPY = analyzer(
    name="clippy",
    languages=RUST_LANGUAGE,
    how="cargo clippy",
    analyses=_clippy,
    rules=defined_by(settings=("clippy",)),
    reads=("clippy",),
)
CLIPPY_ACTIONS = tuple(
    Action(name=name, runs=lambda _inputs: (("cargo", "clippy"),))
    for name in ("actions-rs/clippy-check", "giraffate/clippy-action", "clechasseur/rs-clippy-check")
)

RUST = Ecosystem(
    label="Rust",
    languages=RUST_LANGUAGE,
    build_systems=(CARGO,),
    source_suffixes={".rs": "Rust"},
    toolchain=ToolchainPatterns(
        language="Rust",
        versions=(
            re.compile(rf"\brust-toolchain@{_RUST_VERSION}"),
            re.compile(rf"\btoolchain\W+{_RUST_VERSION}"),
            re.compile(rf"\bcargo\s+\+{_RUST_VERSION}"),
            re.compile(rf"\brustup\s+(?:default|toolchain\s+install|install)\s+{_RUST_VERSION}"),
            re.compile(r"\brust:(\d+\.\d+(?:\.\d+)?)"),
        ),
        usage=re.compile(r"\bcargo\b|\brustup\b|\brustc\b"),
    ),
    rules=(
        RUST_TOOLCHAINS,
        BuildTypes(axis=RUST_TOOLCHAINS),
        WARNINGS,
        HARDENING,
        FunctionLimits(),
        DEPENDENCIES,
        TARGET_DIRECTORY,
        LICENSE,
    ),
)
