import re
import unittest

from project_validator.ecosystems import ToolchainPatterns
from project_validator.facts.jobs import Toolchain
from project_validator.platforms import (
    _language_toolchains,
    detect_compilers,
    detect_operating_systems,
    detect_toolchains,
)


def _toolchains(language: str, *versions: str) -> frozenset[Toolchain]:
    return frozenset(Toolchain(language=language, version=version) for version in versions)


class PlatformDetectionTests(unittest.TestCase):
    def test_detects_runner_labels(self) -> None:
        self.assertEqual(detect_operating_systems("ubuntu-24.04 windows-2022 macos-14"), ["linux", "windows", "macos"])

    def test_detects_compiler_spellings(self) -> None:
        self.assertEqual(detect_compilers("g++-13"), ["gcc"])
        self.assertEqual(detect_compilers("clang++-18"), ["clang"])
        self.assertEqual(detect_compilers("ilammy/msvc-dev-cmd"), ["msvc"])
        self.assertEqual(detect_compilers("CXX=icpx"), ["intel"])

    def test_tools_named_after_compilers_are_not_compilers(self) -> None:
        self.assertEqual(detect_compilers("clang-format clang-tidy clangd gcovr llvm-cov"), [])
        self.assertEqual(detect_compilers("CLANG_TIDY_VERSION: 19.1.1"), [])

    def test_setup_cpp_names_clang_llvm(self) -> None:
        self.assertEqual(detect_compilers("compiler: llvm-19.1.1"), ["clang"])
        self.assertEqual(detect_compilers("./setup_cpp_linux --compiler llvm --cmake true"), ["clang"])
        self.assertEqual(detect_compilers("gcov_executable: llvm-cov gcov"), [])


class ToolchainDetectionTests(unittest.TestCase):
    def test_python_versions(self) -> None:
        self.assertEqual(detect_toolchains('{"python-version": "3.14"}'), _toolchains("Python", "3.14"))
        self.assertEqual(detect_toolchains("python-version: 3.x"), _toolchains("Python", "3.x"))
        self.assertEqual(detect_toolchains("python-version: pypy3.10"), _toolchains("Python", "pypy3.10"))
        self.assertEqual(detect_toolchains("image: python:3.12-slim"), _toolchains("Python", "3.12"))
        self.assertEqual(detect_toolchains("python3.13 -m pytest"), _toolchains("Python", "3.13"))

    def test_rust_toolchains(self) -> None:
        self.assertEqual(detect_toolchains("uses: dtolnay/rust-toolchain@1.85"), _toolchains("Rust", "1.85"))
        self.assertEqual(detect_toolchains('{"toolchain": "nightly-2026-01-01"}'), _toolchains("Rust", "nightly"))
        self.assertEqual(detect_toolchains("cargo +beta test"), _toolchains("Rust", "beta"))
        self.assertEqual(detect_toolchains("rustup toolchain install stable"), _toolchains("Rust", "stable"))
        self.assertEqual(detect_toolchains("image: rust:1.80.1"), _toolchains("Rust", "1.80.1"))

    def test_the_first_text_naming_a_version_wins(self) -> None:
        found = detect_toolchains('{"python": "3.13"}', "python-version: 3.13 # was python-version: 3.11")
        self.assertEqual(found, _toolchains("Python", "3.13", "3.11"))
        found = detect_toolchains("python-version: 3.13", "python-version: 3.11")
        self.assertEqual(found, _toolchains("Python", "3.13"))

    def test_using_a_language_without_a_version_is_the_runner_default(self) -> None:
        self.assertEqual(detect_toolchains("pip install tox && tox"), _toolchains("Python", "default"))
        self.assertEqual(detect_toolchains("cargo build"), _toolchains("Rust", "default"))

    def test_mentioning_a_language_is_not_using_it(self) -> None:
        self.assertEqual(detect_toolchains("languages: python, rust\nname: python-docs\ncmake --version"), frozenset())
        self.assertEqual(detect_toolchains('{"python-version": "${{ matrix.python }}"}'), frozenset())


class LabelledToolchainTests(unittest.TestCase):
    def test_a_toolchain_named_by_a_snapshot_is_written_with_its_label(self) -> None:
        patterns = ToolchainPatterns(
            language="GHC",
            versions=(re.compile(r"\bghc-version\W+(\d+\.\d+)"),),
            usage=re.compile(r"\bstack\b"),
            labelled=((re.compile(r"--resolver[=\s]+(lts-[\d.]+)"), "Stackage {}"),),
        )
        found = _language_toolchains("GHC", patterns, ("stack test --resolver lts-22 && ghc-version: 9.8",))
        self.assertEqual({str(toolchain) for toolchain in found}, {"GHC 9.8", "GHC Stackage lts-22"})
