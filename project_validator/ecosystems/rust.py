"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import re
from pathlib import Path, PurePosixPath

from project_validator.build_configurations import option_values
from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import configuration, existing_texts, first_existing, toml_value
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.coverage import CoverageTool, Granularity, Measurement, measured
from project_validator.facts.expansion import has_option, program
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    Analyzer,
    BuildOutputs,
    BuildTypes,
    DependencyAudit,
    DependencyManagement,
    Formatter,
    FunctionLimits,
    Hardening,
    SecurityLints,
    StaticAnalysis,
    TestSuite,
    WarningPolicy,
    ci_configuration,
    directories,
    ignored_at_top_level,
    toml_license,
)
from project_validator.text import Pattern, pattern


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


CARGO = BuildSystem(
    name="Cargo",
    files=("Cargo.toml",),
    languages=frozenset({"Rust"}),
    is_build_tree=is_cargo_target,
    build_types=cargo_build_types,
)

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


def _cargo(command: Command, name: str) -> tuple[str, ...] | None:
    """The arguments after `cargo [+toolchain] name`, when the command runs that cargo subcommand."""
    argv = tuple(word for word in resolved(command) if not word.startswith("+"))
    return argv[1:] if argv[:2] == ("cargo", name) else None


def _cargo_llvm_cov(command: Command, _: Facts) -> Measurement | None:
    if (argv := _cargo(command, "llvm-cov")) is None:
        return None
    branch = has_option(argv, "--branch")
    return measured(LINE, REGION, BRANCH if branch else None, PATH if has_option(argv, "--mcdc") else None)


def _cargo_tarpaulin(command: Command, _: Facts) -> Measurement | None:
    if (argv := _cargo(command, "tarpaulin")) is None:
        return None
    return measured(LINE, BRANCH if has_option(argv, "--branch", "-b") else None)


def _grcov(command: Command, _: Facts) -> Measurement | None:
    argv = resolved(command)
    if program(argv) != "grcov":
        return None
    return measured(LINE, BRANCH if has_option(argv, "--branch") else None)


_MCDC = re.compile(r"-Z\s*coverage-options=\S*mcdc")


def _rustc_mcdc(command: Command, _: Facts) -> Measurement | None:
    """rustc's MC/DC instrumentation, on a command line or in RUSTFLAGS."""
    words = (" ".join(resolved(command)), command.env.get("RUSTFLAGS", ""))
    return measured(PATH) if any(_MCDC.search(word) for word in words) else None


LINE, REGION, BRANCH, PATH = Granularity.LINE, Granularity.REGION, Granularity.BRANCH, Granularity.PATH
RUST_LANGUAGE = frozenset({"Rust"})
CARGO_LLVM_COV = CoverageTool(
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
CARGO_TARPAULIN = CoverageTool(
    name="cargo-tarpaulin",
    languages=RUST_LANGUAGE,
    can={LINE: "cargo tarpaulin", BRANCH: "cargo tarpaulin --branch"},
    measures=_cargo_tarpaulin,
)
GRCOV = CoverageTool(
    name="grcov", languages=RUST_LANGUAGE, can={LINE: "grcov", BRANCH: "grcov --branch"}, measures=_grcov
)
RUSTC_MCDC = CoverageTool(
    name="rustc MC/DC",
    languages=RUST_LANGUAGE,
    can={PATH: "RUSTFLAGS=-Zcoverage-options=mcdc"},
    measures=_rustc_mcdc,
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

# Forbidding unsafe code crate-wide makes the compiler reject the code whose memory safety it cannot check.
SECURITY_LINTS = SecurityLints(
    texts=_settings_texts,
    lints=(
        _setting(
            "unsafe_code forbidden",
            r"#!\[\s*(?:forbid|deny)\s*\([^)]*\bunsafe_code\b"
            r"""|^\s*unsafe_code\s*=\s*(?:\{[^}]*\blevel\s*=\s*)?["'](?:forbid|deny)["']"""
            r"""|-[FD][\s"',]*unsafe_code\b|--(?:forbid|deny)[=\s]+unsafe_code\b""",
        ),
    ),
)

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        pattern("cargo audit", r"\bcargo[- ]audit\b|\brustsec/audit-check\b|\bactions-rust-lang/audit\b"),
        # cargo deny checks advisories unless told to run only its other checks.
        pattern(
            "cargo deny",
            r"\bcargo[- ]deny\b[^\n]*\bcheck\b(?:[ \t]+advisories\b|(?![ \t]+(?:bans|licenses|sources)\b))"
            r"|\bEmbarkStudios/cargo-deny-action\b",
        ),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="consider running cargo audit (rustsec/audit-check) or cargo deny check advisories in CI",
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

STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(
            name="clippy",
            runs=re.compile(r"\bcargo\s+(?:\+\S+\s+)?clippy\b|\bclippy-check\b"),
            configured=configuration(
                ("clippy.toml", ".clippy.toml"),
                {"Cargo.toml": re.compile(r"^\s*\[(?:workspace\.)?lints\.clippy\]", re.MULTILINE)},
            ),
        ),
    ),
    texts=ci_configuration,
    hint="consider running cargo clippy in CI",
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
        TESTS,
        WARNINGS,
        HARDENING,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(),
        STATIC_ANALYSIS,
        DEPENDENCIES,
        TARGET_DIRECTORY,
        LICENSE,
    ),
)
