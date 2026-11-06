# Rust

Recognised by `.rs` sources and Cargo (`Cargo.toml`).

## `tests-run`

`#[test]` functions run by `cargo test` or nextest.

## `coverage`

cargo-llvm-cov, cargo-tarpaulin or grcov with `--branch`. MC/DC coverage (`cargo llvm-cov --mcdc`) is a bonus.

## `platform-matrix`

The toolchains are Rust toolchains.

## `ci-build-types`

Every OS/toolchain combination builds the debug and release profiles, each with and without sanitizers.

## `compiler-warnings`

`cargo clippy`, `-D warnings` and `clippy::pedantic`.

## `hardening`

`overflow-checks` in release builds.

## `code-formatting`

rustfmt has a default style, so CI enforcement alone passes; its style can be set in `rustfmt.toml`.

## `function-limits`

lizard runs with a length limit.

## `static-analysis`

`cargo clippy`.

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
