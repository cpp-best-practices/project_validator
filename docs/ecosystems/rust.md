# Rust

Recognised by `.rs` sources and Cargo (`Cargo.toml`).

## `tests-run`

`#[test]` functions run by `cargo test`, nextest, llvm-cov or tarpaulin.

## `coverage`

cargo-llvm-cov, cargo-tarpaulin or grcov with `--branch`. MC/DC coverage (`cargo llvm-cov --mcdc`, or
`-Zcoverage-options=mcdc` in RUSTFLAGS) is a bonus.

## `platform-matrix`

The toolchains are Rust toolchains.

## `ci-build-types`

Every OS/toolchain combination builds the debug and release profiles, each with and without sanitizers.

## `compiler-warnings`

`cargo clippy`, `-D warnings` and `clippy::pedantic`.

## `hardening`

`overflow-checks` in release builds.

## `code-formatting`

rustfmt: `cargo fmt --check` (with any toolchain, `cargo +nightly fmt -- --check`), `rustfmt --check`, or the
`actions-rust-lang/rustfmt` action. It has a default style, so CI enforcement alone passes; its style can be set in
`rustfmt.toml` or `.rustfmt.toml`, which applies to the crates at and below it.

## `function-limits`

lizard runs with a length limit.

## `static-analysis`

`cargo clippy` (with any toolchain), or a clippy action; its lints configured in `clippy.toml` or the
`[lints.clippy]` table of Cargo.toml.

## `security-scanning`

`unsafe_code` forbidden crate-wide.

## `dependency-management`

A binary crate commits `Cargo.lock`; a library need not.

## `dependency-audit`

cargo audit, or `cargo deny check` (advisories).

## `license`

`[package] license` in `Cargo.toml`.

## `committed-artifacts`

A top-level `target/`.

## `vcs-ignore`

`/target`.
