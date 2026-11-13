# Nix

Recognised by `flake.nix` (a flake), `default.nix` or `shell.nix` (plain expressions), and `.nix` sources. A CI job
uses Nix when it runs `nix`, `nix-build`, `nix-shell`, one of the tools below or `cachix`, or installs it with
`cachix/install-nix-action`, `DeterminateSystems/nix-installer-action` or `nixbuild/nix-quick-install-action`.

## `tests-run`

A flake's `checks` output, built by `nix flake check` (or `nix build .#checks.<system>.<check>`).

## `code-formatting`

nixfmt or nixpkgs-fmt (`--check`), alejandra (`--check`), each with its one style; or `nix fmt`, the flake's own
`formatter` output, which checks when `--check` (or treefmt's `--fail-on-change`) is passed through:
`nix fmt -- --check .`.

## `static-analysis`

statix (`statix check .`) and deadnix (`deadnix .`).

## `compiler-warnings`

Nix has no compiler warnings; its lints stand in: both statix and deadnix run in CI.

## `warnings-as-errors`

`statix check` fails on any finding; deadnix does with `--fail` (`-f`).

## `platform-matrix`

The axis besides the OS is the system built for: the ones a job names (`x86_64-linux`, `aarch64-linux`,
`aarch64-darwin`, in a matrix or a command), else the runner's own (`x86_64-linux` on Linux, `aarch64-darwin` on
macOS). Two OSes, two systems and three combinations pass, as for every language: a Linux job building
`aarch64-linux` too (with binfmt) beside a macOS one does.

## `vcs-ignore`

`nix build` leaves `result` (and `result-*`) symlinks, which the ignore file must cover.

## `committed-artifacts`

A `result` symlink is a build output, never committed.

## Not judged

`coverage` has no tool for Nix expressions. `flake.lock`, committed and updated automatically (`update-flake-lock`,
Renovate), is a dependency rule (#24). What nix runs in turn is followed (`nix run nixpkgs#statix -- check .` runs
statix; `nix develop -c <command>` and `nix shell … -c <command>` run the command), except `nix-shell --run "…"`,
whose command is a string.
