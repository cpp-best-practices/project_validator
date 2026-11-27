"""Native code another ecosystem's build compiles (upstream #186): an R package's `src/`, a gem's `ext/`, a SwiftPM C
target, OCaml stubs, cgo. The host unit owns the code: the checks that presuppose a C or C++ build of its own (build
types, extensions, an out-of-source build directory, compile_commands.json, a subproject guard, a C/C++ compiler
matrix) skip it, saying which build compiles it; the hygiene checks still judge it, and the flags checks read the
flags the host build passes (`Makevars`, `extconf.rb`)."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.compile_commands import compile_commands
from project_validator.checks.compiler_extensions import compiler_extensions
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.hardening import hardening
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Placed, Result, Status
from project_validator.facts.structure import host_built
from tests.support import make_context, temp_project

WORKFLOW = """\
on: push
jobs:
  check:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: r-lib/actions/setup-r@v2
      - uses: r-lib/actions/check-r-package@v2
"""
R_PACKAGE = {
    "DESCRIPTION": "Package: shop\nVersion: 0.1.0\nTitle: Prices\nLicense: MIT\n",
    "NAMESPACE": "useDynLib(shop)\n",
    "R/prices.R": "price <- function(x) .Call(price_c, x)\n",
    "src/prices.cpp": "int price(int x) { return x; }\n",
    ".github/workflows/check.yml": WORKFLOW,
}
GEM = {
    "Gemfile": 'source "https://rubygems.org"\ngemspec\n',
    "fast.gemspec": 'Gem::Specification.new { |s| s.name = "fast"; s.extensions = ["ext/fast/extconf.rb"] }\n',
    "lib/fast.rb": 'require "fast/fast"\n',
    "ext/fast/fast.c": "void Init_fast(void) {}\n",
    "ext/fast/extconf.rb": "require 'mkmf'\n$CFLAGS << ' -Wall -Wextra -Werror'\ncreate_makefile('fast/fast')\n",
}


def _place(result: Result, language: str) -> Placed:
    found = [place for place in result.places if place.ecosystem == language]
    assert len(found) == 1, result  # noqa: S101 - one place per language here
    return found[0]


def _run(check: Check, files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return check.run(make_context(root))


class HostBuiltTests(unittest.TestCase):
    def test_native_code_with_no_build_of_its_own_belongs_to_its_unit_s_build(self) -> None:
        with temp_project(R_PACKAGE) as root:
            self.assertEqual(host_built(make_context(root).facts), {(".", "C++"): "R package"})
        with temp_project({**R_PACKAGE, "src/CMakeLists.txt": "project(p CXX)\n"}) as root:
            self.assertEqual(host_built(make_context(root).facts), {})  # a C++ build of its own
        with temp_project({"src/main.cpp": "int main() {}\n"}) as root:
            self.assertEqual(host_built(make_context(root).facts), {})  # no build at all: judged as it is

    def test_the_checks_of_a_cxx_build_of_its_own_skip_it(self) -> None:
        for check in (ci_build_types, compiler_extensions, compile_commands):
            with self.subTest(check=check.name):
                place = _place(_run(check, R_PACKAGE), "C++")
                self.assertEqual(place.result.status, Status.SKIP, place.result)
                self.assertIn("built by its R package build, not a C or C++ build of its own", place.result.message)

    def test_the_hygiene_checks_still_judge_it(self) -> None:
        self.assertEqual(_place(_run(static_analysis, R_PACKAGE), "C++").result.status, Status.FAIL)

    def test_the_flags_the_host_build_passes_are_read(self) -> None:
        makevars = {**R_PACKAGE, "src/Makevars": "PKG_CXXFLAGS = -Wall -Wextra -Wpedantic -Wshadow -Wconversion\n"}
        self.assertEqual(_place(_run(compiler_warnings, makevars), "C++").result.status, Status.PASS)
        self.assertEqual(_place(_run(compiler_warnings, R_PACKAGE), "C++").result.status, Status.FAIL)
        hardened = {**R_PACKAGE, "src/Makevars": "PKG_CPPFLAGS = -D_FORTIFY_SOURCE=2\n"}
        self.assertNotEqual(_place(_run(hardening, hardened), "C++").result.status, Status.FAIL)
        self.assertEqual(_place(_run(warnings_as_errors, GEM), "C").result.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()
