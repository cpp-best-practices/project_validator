"""Each package manager's manifests, read for the direct dependencies they declare (upstream #412): by name, the
development's apart, and never the project's own packages."""

from __future__ import annotations

import json
import unittest

from project_validator.c_family.dependencies import _vcpkg_dependencies
from project_validator.ecosystems.go import _go_requirements
from project_validator.ecosystems.php import _composer_dependencies
from project_validator.ecosystems.python import _pyproject_dependencies, _requirements_dependencies
from project_validator.ecosystems.ruby import _gemfile_dependencies, _gemspec_dependencies
from project_validator.ecosystems.rust import _cargo_dependencies
from project_validator.facts.dependencies import Dependencies


def _sorted(found: Dependencies) -> tuple[list[str], list[str]]:
    direct, development = found
    return sorted(direct), sorted(development)


class CargoTests(unittest.TestCase):
    def test_every_target_s_dependencies_and_the_workspace_s(self) -> None:
        text = (
            '[dependencies]\nserde = "1"\n[build-dependencies]\ncc = "1"\n'
            "[target.'cfg(windows)'.dependencies]\nwinapi = \"0.3\"\n"
            "[target.'cfg(unix)'.dev-dependencies]\nnix = \"1\"\n"
            '[workspace.dependencies]\ntokio = "1"\nown = { path = "own" }\n'
        )
        self.assertEqual(
            _sorted(_cargo_dependencies("Cargo.toml", text)), (["cc", "serde", "tokio", "winapi"], ["nix"])
        )


class PythonTests(unittest.TestCase):
    def test_poetry_uv_and_pdm_development_dependencies(self) -> None:
        text = (
            '[tool.poetry.dependencies]\npython = "^3.12"\nhttpx = "*"\nown = { path = "../own" }\n'
            '[tool.poetry.group.test.dependencies]\npytest = "*"\n[tool.poetry.dev-dependencies]\nblack = "*"\n'
            '[tool.uv]\ndev-dependencies = ["ruff"]\n[tool.pdm.dev-dependencies]\nlint = ["mypy>=1"]\n'
        )
        self.assertEqual(
            _sorted(_pyproject_dependencies("pyproject.toml", text)), (["httpx"], ["black", "mypy", "pytest", "ruff"])
        )

    def test_a_requirements_file_named_for_development(self) -> None:
        text = "-e .\nruff==0.6.9  # lint\ngit+https://example.com/x.git\n"
        self.assertEqual(_requirements_dependencies("requirements/test.txt", text), ([], ["ruff"]))
        self.assertEqual(_requirements_dependencies("requirements.txt", text), (["ruff"], []))


class OtherManagerTests(unittest.TestCase):
    def test_composer_leaves_the_platform_out(self) -> None:
        text = json.dumps({"require": {"php": ">=8.2", "ext-json": "*", "monolog/monolog": "^3"}, "require-dev": []})
        self.assertEqual(_composer_dependencies("composer.json", text), (["monolog/monolog"], []))

    def test_a_gemfile_s_development_and_test_groups(self) -> None:
        text = (
            "source 'https://rubygems.org'\ngemspec\ngem 'rails', '~> 7'\n"
            "group :development, :test do\n  gem 'rspec'\nend\n"
            "group :production do\n  gem 'pg'\nend\ngem 'rubocop', group: :development\n"
        )
        self.assertEqual(_gemfile_dependencies("Gemfile", text), (["rails", "pg"], ["rspec", "rubocop"]))

    def test_a_gemspec_s_runtime_and_development_dependencies(self) -> None:
        text = "s.add_dependency 'rack'\ns.add_runtime_dependency('json')\ns.add_development_dependency \"rake\"\n"
        self.assertEqual(_gemspec_dependencies("x.gemspec", text), (["rack", "json"], ["rake"]))

    def test_vcpkg_names_its_ports_by_name_or_in_an_object(self) -> None:
        text = json.dumps({"dependencies": ["fmt", {"name": "boost-asio"}, {"features": []}]})
        self.assertEqual(_vcpkg_dependencies("vcpkg.json", text), (["fmt", "boost-asio"], []))
        self.assertEqual(_vcpkg_dependencies("vcpkg.json", "[]"), ([], []))

    def test_go_mod_leaves_indirect_replaced_and_excluded_modules_out(self) -> None:
        text = (
            "module example.com/m\n\nrequire github.com/a/a v1.0.0\nrequire (\n\tgithub.com/b/b v1.2.0\n"
            "\tgithub.com/c/c v1.0.0 // indirect\n)\nexclude (\n\tgithub.com/d/d v0.1.0\n)\n"
            "replace github.com/a/a => ../a\n"
        )
        self.assertEqual(_go_requirements("go.mod", text), (["github.com/a/a", "github.com/b/b"], []))


if __name__ == "__main__":
    unittest.main()
