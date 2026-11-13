"""Kinds of Nix project, for tests that run a check in every layout: a flake, and plain expressions."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

FLAKE = """\
{
  description = "Prices of the shop";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      forEach = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forEach (pkgs: { default = pkgs.callPackage ./shop.nix { }; });
      checks = forEach (pkgs: { default = pkgs.callPackage ./shop.nix { }; });
      formatter = forEach (pkgs: pkgs.nixfmt-rfc-style);
    };
}
"""
PACKAGE = """\
{ stdenv }:
stdenv.mkDerivation {
  pname = "shop";
  version = "0.1.0";
  src = ./.;
  installPhase = "mkdir -p $out/bin && echo 6 > $out/bin/total";
}
"""

LAYOUTS = (
    ProjectLayout(
        name="Nix flake",
        files={"flake.nix": FLAKE, "shop.nix": PACKAGE},
        languages=frozenset({"Nix"}),
        build_systems=frozenset({"Nix flake"}),
    ),
    ProjectLayout(
        name="Nix expressions",
        files={
            "default.nix": "{ pkgs ? import <nixpkgs> { } }: pkgs.callPackage ./shop.nix { }\n",
            "shop.nix": PACKAGE,
        },
        languages=frozenset({"Nix"}),
        build_systems=frozenset({"Nix"}),
    ),
)
