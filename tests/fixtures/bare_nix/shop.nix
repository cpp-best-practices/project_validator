{ stdenv }:
stdenv.mkDerivation {
  pname = "shop";
  version = "0.1.0";
  src = ./.;
  installPhase = "mkdir -p $out/bin && echo 6 > $out/bin/total";
}
