"""What the validator shows of a project without judging it (upstream #412): the "About the project" details."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.about import Detail, about
from project_validator.analysis import analyse
from project_validator.views import html, text
from tests.support import json_output, make_context, temp_project
from tests.test_cli import run_cli

WORKFLOW = ".github/workflows/ci.yml"


def _about(files: Mapping[str, str]) -> tuple[Detail, ...]:
    with temp_project(files) as root:
        return about(make_context(root).facts)


def _versions(files: Mapping[str, str]) -> dict[str, Detail]:
    return {detail.subject: detail for detail in _about(files) if detail.group == "Versions"}


def _python_ci(*versions: str) -> dict[str, str]:
    steps = [{"uses": "actions/setup-python@v5", "with": {"python-version": "${{ matrix.python }}"}}, {"run": "pytest"}]
    job = {"runs-on": "ubuntu-latest", "strategy": {"matrix": {"python": list(versions)}}, "steps": steps}
    return {WORKFLOW: json.dumps({"jobs": {"test": job}})}


PYPROJECT = '[project]\nname = "app"\nrequires-python = "{}"\n'


class VersionsTest(unittest.TestCase):
    def test_python_shows_what_it_declares_and_pins_beside_what_ci_tests(self) -> None:
        found = _versions(
            {
                "pyproject.toml": PYPROJECT.format(">=3.10"),
                ".python-version": "3.12\n",
                "app.py": "",
                **_python_ci("3.10", "3.12"),
            }
        )["Python"]
        self.assertEqual(
            "supports >=3.10 (pyproject.toml); pins 3.12 (.python-version); CI tests Python versions 3.10, 3.12",
            found.text,
        )
        self.assertEqual(["3.10", "3.12"], found.data["tested"])
        self.assertIsNone(found.data["untested_minimum"])

    def test_the_oldest_version_declared_is_named_when_ci_does_not_test_it(self) -> None:
        found = _versions({"pyproject.toml": PYPROJECT.format(">=3.9"), "app.py": "", **_python_ci("3.12", "3.13")})[
            "Python"
        ]
        self.assertIn("the oldest supported, 3.9, is not tested", found.text)
        self.assertEqual("3.9", found.data["untested_minimum"])

    def test_the_oldest_version_is_not_compared_with_versions_that_are_not_numbers(self) -> None:
        found = _versions({"pyproject.toml": PYPROJECT.format(">=3.9"), "app.py": "", **_python_ci("3.x")})["Python"]
        self.assertNotIn("not tested", found.text)
        self.assertIsNone(found.data["untested_minimum"])

    def test_a_release_line_tested_covers_the_oldest_patch_release_supported(self) -> None:
        go = "module example.com/app\n\ngo 1.22.0\n"
        steps = [{"uses": "actions/setup-go@v5", "with": {"go-version": "1.22"}}, {"run": "go test ./..."}]
        workflow = json.dumps({"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": steps}}})
        found = _versions({"go.mod": go, "main.go": "", WORKFLOW: workflow})["Go"]
        self.assertIn("CI tests Go versions 1.22", found.text)
        self.assertIsNone(found.data["untested_minimum"])

    def test_a_major_version_supported_is_covered_by_any_release_of_it_tested(self) -> None:
        package = json.dumps({"name": "app", "engines": {"node": ">=24"}})
        steps = [{"uses": "actions/setup-node@v4", "with": {"node-version": "24.18.0"}}, {"run": "npm test"}]
        workflow = json.dumps({"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": steps}}})
        found = _versions({"package.json": package, "index.js": "", WORKFLOW: workflow})["JavaScript"]
        self.assertIn("24.18.0", found.text)
        self.assertIsNone(found.data["untested_minimum"])

    def test_the_same_declaration_in_several_packages_is_said_once(self) -> None:
        package = json.dumps({"name": "app", "engines": {"node": ">=18"}})
        files = {f"packages/{name}/package.json": package for name in ("a", "b", "c")}
        found = _versions({"package.json": package, **files, "index.js": ""})["JavaScript"]
        self.assertEqual("supports node >=18 (package.json and 3 more)", found.text.split("; ")[0])
        declared = found.data["declared"]
        self.assertIsInstance(declared, list)
        self.assertEqual(4, len(declared) if isinstance(declared, list) else 0)

    def test_a_language_ci_tests_without_declaring_a_version_says_so(self) -> None:
        found = _versions({"app.py": "", **_python_ci("3.12")})["Python"]
        self.assertEqual("declares no version; CI tests Python versions 3.12", found.text)

    def test_rust_shows_its_minimum_and_its_toolchain(self) -> None:
        found = _versions(
            {
                "Cargo.toml": '[package]\nname = "app"\nrust-version = "1.70"\n',
                "rust-toolchain.toml": '[toolchain]\nchannel = "1.75.0"\n',
                "src/main.rs": "",
            }
        )["Rust"]
        self.assertTrue(found.text.startswith("supports 1.70 (Cargo.toml); pins 1.75.0 (rust-toolchain.toml)"))

    def test_a_plain_rust_toolchain_file_pins_its_channel(self) -> None:
        found = _versions({"Cargo.toml": '[package]\nname = "app"\n', "rust-toolchain": "nightly\n", "src/main.rs": ""})
        self.assertIn("pins nightly (rust-toolchain)", found["Rust"].text)

    def test_go_shows_its_go_directive_and_toolchain(self) -> None:
        found = _versions({"go.mod": "module example.com/app\n\ngo 1.22\n\ntoolchain go1.22.3\n", "main.go": ""})
        self.assertIn("supports 1.22 (go.mod); pins 1.22.3 (go.mod)", found["Go"].text)

    def test_node_shows_its_engines_and_its_pinned_version(self) -> None:
        package = json.dumps({"name": "app", "engines": {"node": ">=18"}})
        found = _versions({"package.json": package, ".nvmrc": "v20\n", "index.js": ""})
        self.assertIn("supports node >=18 (package.json); pins v20 (.nvmrc)", found["JavaScript"].text)

    def test_cpp_shows_the_standard_its_build_sets(self) -> None:
        cmake = "project(app CXX)\nset(CMAKE_CXX_STANDARD 20)\nadd_executable(app main.cpp)\n"
        found = _versions({"CMakeLists.txt": cmake, "main.cpp": ""})
        self.assertTrue(found["C++"].text.startswith("supports C++20 (CMakeLists.txt)"))

    def test_cpp_shows_the_standard_a_target_requires(self) -> None:
        cmake = "project(app CXX)\nadd_executable(app main.cpp)\ntarget_compile_features(app PUBLIC cxx_std_17)\n"
        found = _versions({"CMakeLists.txt": cmake, "main.cpp": ""})
        self.assertTrue(found["C++"].text.startswith("supports C++17 (CMakeLists.txt)"))

    def test_meson_shows_its_standard_option(self) -> None:
        meson = "project('app', 'cpp', default_options: ['cpp_std=c++20'])\nexecutable('app', 'main.cpp')\n"
        found = _versions({"meson.build": meson, "main.cpp": ""})
        self.assertTrue(found["C++"].text.startswith("supports c++20 (meson.build)"))

    def test_only_the_products_own_languages_and_declarations_are_shown(self) -> None:
        found = _versions(
            {
                "pyproject.toml": PYPROJECT.format(">=3.10"),
                "app.py": "",
                "tests/fixtures/go_project/go.mod": "module example.com/fixture\n\ngo 1.21\n",
                "tests/fixtures/go_project/main.go": "",
                "tests/fixtures/py_project/.python-version": "3.8\n",
            }
        )
        self.assertEqual(["Python"], list(found))
        self.assertEqual("supports >=3.10 (pyproject.toml)", found["Python"].text.split("; ")[0])
        self.assertNotIn("3.8", found["Python"].text)

    def test_a_project_whose_only_code_is_tests_shows_their_language(self) -> None:
        found = _versions({"tests/test_app.py": "", **_python_ci("3.12")})
        self.assertEqual("declares no version; CI tests Python versions 3.12", found["Python"].text)

    def test_a_project_that_declares_and_tests_nothing_shows_no_versions(self) -> None:
        self.assertEqual({}, _versions({"app.py": ""}))


SHOWN = {"pyproject.toml": PYPROJECT.format(">=3.10"), "app.py": "", **_python_ci("3.10", "3.12")}
LINE = "Versions (Python): supports >=3.10 (pyproject.toml); CI tests Python versions 3.10, 3.12"


class ViewsTest(unittest.TestCase):
    def test_the_text_report_shows_the_details_after_what_was_detected(self) -> None:
        with temp_project(SHOWN) as root:
            shown = text.render(analyse(make_context(root), ()))
        self.assertIn("About the project (shown, never judged):\n  " + LINE, shown)
        self.assertLess(shown.index("Detected:"), shown.index("About the project"))

    def test_the_html_report_shows_the_details_in_their_own_card(self) -> None:
        with temp_project(SHOWN) as root:
            shown = html.render(analyse(make_context(root), ()))
        self.assertIn('id="about"', shown)
        self.assertIn("supports &gt;=3.10 (pyproject.toml)", shown)

    def test_the_json_results_hold_the_details_under_about(self) -> None:
        with temp_project(SHOWN) as root:
            _code, output, _errors = run_cli("--format", "json", "--only", "coverage", str(root))
        found = json.loads(output)
        json_output(output, "results")
        self.assertEqual(["Versions"], [detail["group"] for detail in found["about"]])
        self.assertEqual(["3.10", "3.12"], found["about"][0]["data"]["tested"])

    def test_a_project_with_nothing_to_show_has_no_section(self) -> None:
        with temp_project({"README.md": "# app\n"}) as root:
            self.assertNotIn("About the project", text.render(analyse(make_context(root), ())))


if __name__ == "__main__":
    unittest.main()
