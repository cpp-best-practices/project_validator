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
