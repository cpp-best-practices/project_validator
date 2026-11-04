"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import re
from pathlib import Path

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import first_existing
from project_validator.rules import BuildTypes, Formatter
from project_validator.text import pattern


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
    rules=(RUST_TOOLCHAINS, BuildTypes(axis=RUST_TOOLCHAINS), RUSTFMT),
)
