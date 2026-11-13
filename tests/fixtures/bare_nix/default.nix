{ pkgs ? import <nixpkgs> { } }:
pkgs.callPackage ./shop.nix { }
