"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import re
from pathlib import Path, PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import existing_texts, first_existing
from project_validator.rules import (
    BuildTypes,
    CoverageTools,
    Formatter,
    FunctionLimits,
    Hardening,
    TestSuite,
    WarningPolicy,
)
from project_validator.text import Pattern, pattern


def is_cargo_target(directory: Path) -> bool:
    """Cargo tags its output with CACHEDIR.TAG and, by default, puts it in `target/` beside `Cargo.toml`."""
    return (directory / "CACHEDIR.TAG").is_file() or (
        directory.name == "target" and (directory.parent / "Cargo.toml").is_file()
    )


CARGO = BuildSystem(name="Cargo", files=("Cargo.toml",), languages=frozenset({"Rust"}), is_build_tree=is_cargo_target)

_RUST_VERSION = r"(stable|beta|nightly|\d+\.\d+(?:\.\d+)?)"

RUST_TOOLCHAINS = versions_axis("Rust toolchain", "Rust")


def _rustfmt_file(context: Context) -> str | None:
    return first_existing(context, ("rustfmt.toml", ".rustfmt.toml"))


RUSTFMT = Formatter(
    name="rustfmt",
    config_file=_rustfmt_file,
    runs=(pattern("rustfmt", r"\bcargo\s+(?:\+\S+\s+)?fmt\b|(?<![\w.-])rustfmt\b(?!\.toml)"),),
    hint="consider a CI job that runs cargo fmt --check",
    default_style=True,
)


def _ci_texts(context: Context) -> tuple[str, ...]:
    return context.ci_texts


COVERAGE = CoverageTools(
    searched="CI configuration",
    texts=_ci_texts,
    branch=(
        pattern("cargo-llvm-cov", r"\bcargo\s+(\+\S+\s+)?llvm-cov\b[^\n]*--branch\b"),
        pattern("cargo-tarpaulin", r"\bcargo\s+(\+\S+\s+)?tarpaulin\b[^\n]*(--branch\b|\s-b\b)"),
        pattern("grcov", r"\bgrcov\b[^\n]*--branch\b"),
    ),
    path=(
        pattern("cargo-llvm-cov MC/DC", r"\bllvm-cov\b[^\n]*--mcdc\b"),
        pattern("rustc MC/DC", r"-Z\s*coverage-options=\S*mcdc"),
    ),
    path_hint="consider adding MC/DC coverage (e.g. cargo llvm-cov --mcdc)",
)

RUST_TEST = re.compile(r"#\[(?:\w+::)*test\b")
RUNS_RUST_TESTS = (pattern("cargo test", r"\bcargo\s+(\+\S+\s+)?(test|nextest|llvm-cov|tarpaulin)\b"),)


def _rust_tests_result(context: Context) -> Result:
    sources = (path for path in context.project.files() if path.endswith(".rs"))
    count = sum(1 for path in sources if RUST_TEST.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no Rust tests found (#[test] functions)")
    return Result.passed(f"Rust tests found in {count} file(s)")


TESTS = TestSuite(found=_rust_tests_result, runs=RUNS_RUST_TESTS, runner="cargo test")

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

HARDENING = Hardening(
    texts=_settings_texts,
    options=(
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
    ),
)

RUST = Ecosystem(
    label="Rust",
    languages=frozenset({"Rust"}),
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
        RUSTFMT,
        COVERAGE,
        TESTS,
        WARNINGS,
        HARDENING,
        FunctionLimits(),
    ),
)
