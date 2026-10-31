import unittest

from project_validator.platforms import detect_compilers, detect_operating_systems


class PlatformDetectionTests(unittest.TestCase):
    def test_detects_runner_labels(self) -> None:
        self.assertEqual(
            detect_operating_systems("ubuntu-24.04 windows-2022 macos-14"), ["linux", "windows", "macos"]
        )

    def test_detects_compiler_spellings(self) -> None:
        self.assertEqual(detect_compilers("g++-13"), ["gcc"])
        self.assertEqual(detect_compilers("clang++-18"), ["clang"])
        self.assertEqual(detect_compilers("ilammy/msvc-dev-cmd"), ["msvc"])
        self.assertEqual(detect_compilers("CXX=icpx"), ["intel"])

    def test_tools_named_after_compilers_are_not_compilers(self) -> None:
        self.assertEqual(detect_compilers("clang-format clang-tidy clangd gcovr llvm-cov"), [])
