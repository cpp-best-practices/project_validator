import unittest

from project_validator.build_configurations import BuildConfiguration, detect_build_types, detect_configurations


class DetectBuildTypesTests(unittest.TestCase):
    def test_cmake_build_type_definition(self) -> None:
        self.assertEqual(detect_build_types("cmake -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo"), {"release"})
        self.assertEqual(detect_build_types("cmake -D CMAKE_BUILD_TYPE=Debug"), {"debug"})

    def test_multi_config_options(self) -> None:
        self.assertEqual(detect_build_types("cmake --build build --config MinSizeRel"), {"release"})
        self.assertEqual(detect_build_types("ctest --test-dir build -C Debug"), {"debug"})

    def test_matrix_axis(self) -> None:
        self.assertEqual(detect_build_types('{"build_type": "Release"}'), {"release"})
        self.assertEqual(detect_build_types('{"BUILD_TYPE": "Debug"}'), {"debug"})

    def test_unknown_or_unresolved_values_are_ignored(self) -> None:
        self.assertEqual(detect_build_types("-DCMAKE_BUILD_TYPE=${{ env.TYPE }} --config Coverage"), set())

    def test_cargo_profiles(self) -> None:
        self.assertEqual(detect_build_types("cargo build && cargo +nightly test --release"), {"debug", "release"})
        self.assertEqual(detect_build_types("cargo nextest run --profile=release"), {"release"})

    def test_cargo_commands_end_at_the_shell_command(self) -> None:
        self.assertEqual(detect_build_types('{"run": "cargo test\\ncargo doc --release"}'), {"debug"})
        self.assertEqual(detect_build_types("cargo test; echo --release"), {"debug"})

    def test_custom_cargo_profiles_and_non_building_commands_are_ignored(self) -> None:
        self.assertEqual(detect_build_types("cargo test --profile ci && cargo clippy --release"), set())


class DetectConfigurationsTests(unittest.TestCase):
    def test_sanitizers_enabled_by_flags_or_options(self) -> None:
        for text in (
            '-DCMAKE_CXX_FLAGS="-fsanitize=address,undefined"',
            "/fsanitize=address",
            "-Dmyproject_ENABLE_SANITIZER_ADDRESS:BOOL=ON -Dmyproject_ENABLE_SANITIZER_MEMORY=OFF",
            '{"sanitizer": "thread"}',
            'RUSTFLAGS="-Zsanitizer=address"',
            "-Dmyproject_PACKAGING_MAINTAINER_MODE:BOOL=OFF",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    detect_configurations(f"{text} -DCMAKE_BUILD_TYPE=Debug"),
                    {BuildConfiguration(build_type="debug", sanitizers=True)},
                )

    def test_sanitizers_disabled_without_evidence_or_explicitly(self) -> None:
        for text in ("", "-DENABLE_SANITIZERS=OFF", '{"sanitizer": "none"}', "-DX_PACKAGING_MAINTAINER_MODE=ON"):
            with self.subTest(text=text):
                self.assertEqual(
                    detect_configurations(f"{text} --config Release"),
                    {BuildConfiguration(build_type="release", sanitizers=False)},
                )

    def test_no_build_type_means_no_configuration(self) -> None:
        self.assertEqual(detect_configurations("-fsanitize=address"), set())
