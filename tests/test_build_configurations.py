"""Build configurations: the build types each build system reads from its commands, and sanitizers."""

import unittest

from project_validator.build_configurations import BuildConfiguration, build_type_kinds, option_values
from project_validator.ecosystems.c_cpp.cmake import cmake_build_types
from project_validator.ecosystems.c_cpp.meson import meson_build_types
from project_validator.ecosystems.rust import cargo_build_types
from tests.support import ci_jobs, command, github_job


class CMakeBuildTypeTests(unittest.TestCase):
    def test_the_build_type_a_configuration_defines(self) -> None:
        self.assertEqual(cmake_build_types(command("cmake -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo")), {"release"})
        self.assertEqual(cmake_build_types(command("cmake -S . -D CMAKE_BUILD_TYPE=Debug")), {"debug"})
        self.assertEqual(
            cmake_build_types(command("emcmake cmake -DCMAKE_BUILD_TYPE=$TYPE", {"TYPE": "Debug"})), {"debug"}
        )

    def test_the_environment_variable_counts_when_configuring(self) -> None:
        self.assertEqual(
            cmake_build_types(command("cmake -S . -B build", {"CMAKE_BUILD_TYPE": "Release"})), {"release"}
        )
        self.assertEqual(cmake_build_types(command("cmake --build build", {"CMAKE_BUILD_TYPE": "Release"})), set())

    def test_multi_config_builds_and_tests(self) -> None:
        self.assertEqual(cmake_build_types(command("cmake --build build --config MinSizeRel")), {"release"})
        self.assertEqual(cmake_build_types(command("ctest --test-dir build -C Debug")), {"debug"})
        self.assertEqual(cmake_build_types(command("ctest.exe --build-config=Release")), {"release"})

    def test_unknown_or_unresolved_values_and_other_programs_build_nothing(self) -> None:
        self.assertEqual(
            cmake_build_types(command("cmake -DCMAKE_BUILD_TYPE=${{ env.TYPE }} --config Coverage")), set()
        )
        self.assertEqual(cmake_build_types(command("echo -DCMAKE_BUILD_TYPE=Debug")), set())


class MesonBuildTypeTests(unittest.TestCase):
    def test_the_build_type_setup_chooses(self) -> None:
        for line, expected in (
            ("meson setup build --buildtype=debugoptimized", {"release"}),
            ("meson setup build --buildtype release", {"release"}),
            ("meson setup build -Dbuildtype=minsize", {"release"}),
            ("meson configure build -D buildtype=debug", {"debug"}),
            ("meson setup build", {"debug"}),  # Meson's default
            ("meson setup build --buildtype=plain", set()),
            ("meson configure build", set()),
            ("meson test -C build", set()),
        ):
            with self.subTest(line=line):
                self.assertEqual(meson_build_types(command(line)), expected)


class CargoBuildTypeTests(unittest.TestCase):
    def test_profiles(self) -> None:
        for line, expected in (
            ("cargo build", {"debug"}),
            ("cargo +nightly test --release", {"release"}),
            ("cargo nextest run --profile=release", {"release"}),
            ("cargo test --profile ci", set()),
            ("cargo clippy --release", set()),
            ("cargo doc --release", set()),
        ):
            with self.subTest(line=line):
                self.assertEqual(cargo_build_types(command(line)), expected)


class OptionTests(unittest.TestCase):
    def test_option_values_in_every_spelling(self) -> None:
        argv = ("ctest", "-C", "Debug", "--build-config=Release", "-CRelWithDebInfo", "-C")
        self.assertEqual(option_values(argv, "-C", "--build-config"), ["Debug", "Release", "RelWithDebInfo"])

    def test_build_type_kinds(self) -> None:
        self.assertEqual(build_type_kinds("RelWithDebInfo", "DEBUG", "Coverage"), {"release", "debug"})


class JobConfigurationTests(unittest.TestCase):
    def _configurations(self, *steps: str) -> set[BuildConfiguration]:
        [job] = ci_jobs(github_job("ubuntu-latest", *steps))
        return set(job.configurations)

    def test_sanitizers_enabled_by_flags_or_options(self) -> None:
        for text in (
            '-DCMAKE_CXX_FLAGS="-fsanitize=address,undefined"',
            "-Dmyproject_ENABLE_SANITIZER_ADDRESS:BOOL=ON -Dmyproject_ENABLE_SANITIZER_MEMORY=OFF",
            "-Dmyproject_PACKAGING_MAINTAINER_MODE:BOOL=OFF",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self._configurations(f"cmake -S . {text} -DCMAKE_BUILD_TYPE=Debug"),
                    {BuildConfiguration(build_type="debug", sanitizers=True)},
                )
        rust = self._configurations('RUSTFLAGS="-Zsanitizer=address" cargo +nightly test')
        self.assertEqual(rust, {BuildConfiguration(build_type="debug", sanitizers=True)})

    def test_sanitizers_disabled_without_evidence_or_explicitly(self) -> None:
        for text in ("", "-DENABLE_SANITIZERS=OFF", "-DX_PACKAGING_MAINTAINER_MODE=ON"):
            with self.subTest(text=text):
                self.assertEqual(
                    self._configurations(f"cmake -S . {text}", "cmake --build build --config Release"),
                    {BuildConfiguration(build_type="release", sanitizers=False)},
                )

    def test_a_matrix_value_no_command_uses_builds_nothing(self) -> None:
        [job] = ci_jobs(github_job("ubuntu-latest", "cmake -S . -B build", matrix={"build_type": ["Release"]}))
        self.assertEqual(job.configurations, frozenset())

    def test_no_build_type_means_no_configuration(self) -> None:
        self.assertEqual(self._configurations("clang++ -fsanitize=address main.cpp"), set())
