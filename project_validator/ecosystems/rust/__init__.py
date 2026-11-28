"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toml_members, toolchain_patterns
from project_validator.facts import Command, resolved
from project_validator.facts.arguments import option_values
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import Dependencies, Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action, joined
from project_validator.facts.history import package_version_reader
from project_validator.facts.licenses import declared_license_reader, toml_license
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.versions import declared_version_reader, pinned_file, toml_version


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


def cargo_profile_build_types(command: Command, read: Callable[[str], str | None]) -> frozenset[str]:
    """The build type of a custom profile (`cargo build --profile fast`): the one of the built-in profile it
    inherits from, through Cargo.toml's `[profile.<name>] inherits` (ripgrep's release-lto)."""
    argv = [word for word in resolved(command) if not word.startswith("+")]
    if argv[:1] != ["cargo"] or not any(tuple(argv[1 : 1 + len(sub)]) == sub for sub in _CARGO_BUILDS):
        return frozenset()
    profiles = option_values(tuple(argv), "--profile")
    text = read(joined(command.directory, "Cargo.toml")) if profiles else None
    if not profiles or text is None:
        return frozenset()
    try:
        declared = tomllib.loads(text).get("profile", {})
    except tomllib.TOMLDecodeError:
        return frozenset()
    name, seen = profiles[0], set()
    while isinstance(declared, dict) and name not in _BUILT_IN_PROFILES and name not in seen:
        seen.add(name)
        found = declared.get(name)
        name = str(found.get("inherits", "")) if isinstance(found, dict) else ""
    return frozenset({_BUILT_IN_PROFILES[name]}) if name in _BUILT_IN_PROFILES else frozenset()


_BUILT_IN_PROFILES = {"release": "release", "bench": "release", "dev": "debug", "test": "debug"}
RUST_LANGUAGE = frozenset({"Rust"})

# cargo's toolchain and the global options it takes before its subcommand, as a regular expression of one of them.
CARGO_OPTIONS = r"(?:\+\S+|--config[=\s]\S+|-Z\s*\S+|-C\s+\S+|--color[=\s]\S+|--locked|--frozen|--offline|-[qv]+)"
_CARGO_OPTION = re.compile(CARGO_OPTIONS)
_CARGO_VALUED = frozenset({"--config", "-Z", "-C", "--color"})


def cargo_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    """A cargo command without its toolchain and the global options before its subcommand (`cargo +nightly --config
    ci.toml clippy -D warnings` is `cargo clippy -D warnings`); any other command as it is."""
    if argv[:1] != ("cargo",):
        return argv
    words = list(argv[1:])
    while words and _CARGO_OPTION.fullmatch(words[0]):
        words.pop(0)
    while len(words) > 1 and words[0] in _CARGO_VALUED:
        del words[:2]
        while words and _CARGO_OPTION.fullmatch(words[0]):
            words.pop(0)
    return ("cargo", *words)


def _cargo_package(text: str) -> bool:
    """Whether a Cargo.toml below another is a project of its own: a package, or a workspace (not a manifest that
    only sets a virtual workspace's members' shared settings)."""
    return bool(re.search(r"^\[(package|workspace)\]", text, re.MULTILINE))


def _path_dependencies(text: str) -> tuple[str, ...]:
    """The directories of the crates a Cargo.toml depends on by path, in any of its dependency tables."""
    try:
        manifest = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return ()
    targets = manifest.get("target")
    holders = [manifest, *(targets.values() if isinstance(targets, dict) else ())]
    kinds = ("dependencies", "dev-dependencies", "build-dependencies")
    tables = [holder.get(kind) for holder in holders if isinstance(holder, dict) for kind in kinds]
    specs = (spec for table in tables if isinstance(table, dict) for spec in table.values() if isinstance(spec, dict))
    return tuple(dict.fromkeys(spec["path"] for spec in specs if isinstance(spec.get("path"), str)))


CARGO = BuildSystem(
    name="Cargo",
    files=("Cargo.toml",),
    languages=RUST_LANGUAGE,
    is_build_tree=is_cargo_target,
    build_types=cargo_build_types,
    configured_build_types=cargo_profile_build_types,
    members=toml_members("workspace"),
    standalone=_cargo_package,
    path_dependencies=_path_dependencies,
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
RUST_VERSION = declared_version_reader(
    name="Cargo.toml rust-version",
    files=("Cargo.toml",),
    language="Rust",
    declares=toml_version(("package", "rust-version"), ("workspace", "package", "rust-version")),
)


def _crate_name(text: str) -> Iterator[tuple[str, bool]]:
    """The name a Cargo.toml publishes its crate under on crates.io: none for `publish = false`, or a list of
    registries without crates.io."""
    package = tomllib.loads(text).get("package")
    found = package if isinstance(package, dict) else {}
    publish = found.get("publish", True)
    if isinstance(name := found.get("name"), str) and (publish is True or "crates-io" in (publish or ())):
        yield name, False


CARGO_VERSION = package_version_reader(
    name="Cargo.toml version",
    files=("Cargo.toml",),
    declares=toml_version(("package", "version"), ("workspace", "package", "version")),
    named=_crate_name,
)
_TOOLCHAIN_CHANNEL = toml_version(("toolchain", "channel"), pinned=True)


def _rust_toolchain(text: str) -> Iterator[tuple[str, bool]]:
    """`rust-toolchain`: a `[toolchain]` table, like `rust-toolchain.toml`, or the older file that holds only the
    channel."""
    try:
        yield from _TOOLCHAIN_CHANNEL(text)
    except ValueError:
        yield from pinned_file(text)


RUST_TOOLCHAIN = declared_version_reader(
    name="rust-toolchain", files=("rust-toolchain.toml", "rust-toolchain"), language="Rust", declares=_rust_toolchain
)


DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def _cargo_declares(_path: str, text: str) -> bool:
    """Cargo manages the dependencies a crate (or its workspace) declares in Cargo.toml."""
    manifest = tomllib.loads(text)
    workspace = manifest.get("workspace")
    tables = [manifest.get(table) for table in DEPENDENCY_TABLES]
    return any(tables) or (isinstance(workspace, dict) and bool(workspace.get("dependencies")))


def _named(table: object) -> Iterator[str]:
    """The dependencies a table names, but the project's own (`path = ...`)."""
    for name, value in table.items() if isinstance(table, dict) else ():
        if not (isinstance(value, dict) and "path" in value):
            yield name


def _cargo_dependencies(_path: str, text: str) -> Dependencies:
    """A crate's (and its workspace's) dependencies, for every target; its dev-dependencies are its development's."""
    manifest = tomllib.loads(text)
    targets = manifest.get("target")
    scopes = [manifest, *(targets.values() if isinstance(targets, dict) else ())]
    workspace = manifest.get("workspace")
    direct = [
        *(
            name
            for scope in scopes
            if isinstance(scope, dict)
            for table in ("dependencies", "build-dependencies")
            for name in _named(scope.get(table))
        ),
        *_named(workspace.get("dependencies") if isinstance(workspace, dict) else None),
    ]
    development = [
        name for scope in scopes if isinstance(scope, dict) for name in _named(scope.get("dev-dependencies"))
    ]
    return direct, development


CARGO_MANIFESTS = manifest_reader(
    name="Cargo dependencies",
    manager="Cargo",
    files=("Cargo.toml",),
    declares=_cargo_declares,
    lists=_cargo_dependencies,
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
    links={"Rust": "https://www.rust-lang.org/"},
    languages=RUST_LANGUAGE,
    build_systems=(CARGO,),
    source_suffixes={".rs": "Rust"},
    toolchain=toolchain_patterns(
        "Rust",
        images=("rust",),
        more=(
            rf"\brust-toolchain@{_RUST_VERSION}",
            # rust-toolchain's `toolchain:` input, not a cache key's `…-toolchain-9.14.1`.
            rf"\btoolchain[\"']?\s*:\s*[\"']?{_RUST_VERSION}",
            rf"\bcargo\s+\+{_RUST_VERSION}",
            rf"\brustup\s+(?:default|toolchain\s+install|install)\s+{_RUST_VERSION}",
        ),
        programs=("cargo", "rustup", "rustc"),
        # rustup runs the toolchain these name for every cargo in the project that names none.
        pinned_by=(
            ("rust-toolchain.toml", re.compile(r"^\s*channel\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)),
            ("rust-toolchain", re.compile(r"^\s*(?:channel\s*=\s*[\"'])?([\w.-]+)", re.MULTILINE)),
        ),
    ),
)
