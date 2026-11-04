"""Rust: built with Cargo, judged by the Rust toolchains CI runs."""

import re
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis


def is_cargo_target(directory: Path) -> bool:
    """Cargo tags its output with CACHEDIR.TAG and, by default, puts it in `target/` beside `Cargo.toml`."""
    return (directory / "CACHEDIR.TAG").is_file() or (
        directory.name == "target" and (directory.parent / "Cargo.toml").is_file()
    )


CARGO = BuildSystem(name="Cargo", files=("Cargo.toml",), languages=frozenset({"Rust"}), is_build_tree=is_cargo_target)

_RUST_VERSION = r"(stable|beta|nightly|\d+\.\d+(?:\.\d+)?)"

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
    axis=versions_axis("Rust toolchain", "Rust"),
)
