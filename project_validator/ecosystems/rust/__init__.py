"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import tomllib
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toml_members, toolchain_patterns
from project_validator.facts import Command, resolved
from project_validator.facts.arguments import option_values
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.licenses import declared_license_reader, toml_license
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level


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


RUST_TOOLCHAINS = versions_axis("Rust toolchain", "Rust", RUST_LANGUAGE, compiled=True)


CRATE_SETTINGS_FILES = frozenset({"Cargo.toml", "lib.rs", "main.rs"})


CARGO_AUDIT_ACTIONS = tuple(
    Action(name=name, runs=lambda _inputs: (("cargo", "audit"),))
    for name in ("rustsec/audit-check", "actions-rust-lang/audit")
)


TARGET_DIRECTORY = BuildOutput(
    languages=RUST_LANGUAGE,
    name="the target directory",
    globs=ignored_at_top_level("target"),
    paths=directories("target"),
    hint="consider ignoring /target",
    artifacts=("/target/",),
)


CARGO_LICENSE = declared_license_reader(
    name="Cargo.toml license", files=("Cargo.toml",), languages=RUST_LANGUAGE, declared=toml_license("package")
)


DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def _cargo_declares(_path: str, text: str) -> bool:
    """Cargo manages the dependencies a crate (or its workspace) declares in Cargo.toml."""
    manifest = tomllib.loads(text)
    workspace = manifest.get("workspace")
    tables = [manifest.get(table) for table in DEPENDENCY_TABLES]
    return any(tables) or (isinstance(workspace, dict) and bool(workspace.get("dependencies")))


CARGO_MANIFESTS = manifest_reader(
    name="Cargo dependencies",
    manager="Cargo",
    files=("Cargo.toml",),
    declares=_cargo_declares,
    application=lambda _path, text: "[[bin]]" in text,
)


# A crate with a binary target (src/main.rs, or src/bin/) is an application.
CARGO_BINARIES = manifest_reader(
    name="Cargo binaries",
    manager="Cargo",
    files=("src/main.rs", "src/bin/*.rs"),
    declares=lambda _path, _text: False,
    application=lambda _path, _text: True,
)


CARGO_LOCK = lockfile_reader(manager="Cargo", files=("Cargo.lock",))


# A binary's builds should be reproducible, so it commits Cargo.lock; a library's users resolve their own.
CARGO_PACKAGES = PackageManager(
    name="Cargo",
    languages=RUST_LANGUAGE,
    lock=Lock.APPLICATIONS,
    applications_by_default=False,
    lock_hint="commit Cargo.lock, so the binary is always built with the dependencies it was tested with",
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
    toolchain=toolchain_patterns(
        "Rust",
        images=("rust",),
        more=(
            rf"\brust-toolchain@{_RUST_VERSION}",
            rf"\btoolchain\W+{_RUST_VERSION}",
            rf"\bcargo\s+\+{_RUST_VERSION}",
            rf"\brustup\s+(?:default|toolchain\s+install|install)\s+{_RUST_VERSION}",
        ),
        commands=r"\bcargo\b|\brustup\b|\brustc\b",
    ),
)
