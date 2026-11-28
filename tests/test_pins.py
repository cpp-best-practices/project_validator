"""The versions a project pins its tools at (upstream #412): read from its files and from CI's install commands and
actions, exact versions only."""

from __future__ import annotations

import unittest

from project_validator.facts.pins import _command, exact
from project_validator.tools.pins import _package_json, _pre_commit, _requirements


def _pinned(facts: object) -> list[tuple[str, str]]:
    return [(fact.package, fact.version) for fact in facts]  # type: ignore[attr-defined]


class ExactTests(unittest.TestCase):
    def test_an_exact_version_and_not_a_range(self) -> None:
        self.assertEqual(
            [exact(text) for text in ("v0.6.9", "24.8.0", "1.0.0-rc.1", " 2.1 ")],
            ["0.6.9", "24.8.0", "1.0.0-rc.1", "2.1"],
        )
        self.assertEqual([exact(text) for text in ("^3.3.0", ">=8", "~1.2", "v6", "latest", "main")], [""] * 6)


class CommandTests(unittest.TestCase):
    def test_python_installers(self) -> None:
        self.assertEqual(
            list(_command(("pip", "install", "black[jupyter]==24.8.0", "isort>=5"))), [("black", "24.8.0")]
        )
        self.assertEqual(list(_command(("python", "-m", "pip", "install", "mypy==1.11.2"))), [("mypy", "1.11.2")])
        self.assertEqual(list(_command(("uv", "tool", "install", "ruff==0.6.9"))), [("ruff", "0.6.9")])
        self.assertEqual(list(_command(("pip", "download", "ruff==0.6.9"))), [])

    def test_node_installers_and_runners(self) -> None:
        self.assertEqual(list(_command(("npm", "install", "-g", "eslint@9.1.0"))), [("eslint", "9.1.0")])
        self.assertEqual(list(_command(("npx", "@biomejs/biome@1.9.4", "ci"))), [("@biomejs/biome", "1.9.4")])
        self.assertEqual(list(_command(("npm",))), [])

    def test_go_install_names_the_program_not_a_major_version(self) -> None:
        argv = ("go", "install", "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.1.0")
        self.assertEqual(list(_command(argv)), [("golangci-lint", "v2.1.0")])
        self.assertEqual(
            list(_command(("go", "install", "honnef.co/go/tools/cmd/staticcheck@latest"))), [("staticcheck", "latest")]
        )

    def test_cargo_install_s_three_ways_of_naming_a_version(self) -> None:
        self.assertEqual(
            list(_command(("cargo", "install", "--locked", "cargo-audit", "--version", "0.20.0"))),
            [("cargo-audit", "0.20.0")],
        )
        self.assertEqual(
            list(_command(("cargo", "install", "cargo-deny", "--version=0.16.1"))), [("cargo-deny", "0.16.1")]
        )
        self.assertEqual(list(_command(("cargo", "install", "cargo-nextest@0.9.72"))), [("cargo-nextest", "0.9.72")])
        self.assertEqual(list(_command(("cargo", "install", "--version", "1.0"))), [])


class FileTests(unittest.TestCase):
    def test_a_frozen_commit_is_the_tag_its_comment_names(self) -> None:
        text = (
            "repos:\n"
            "- repo: https://github.com/psf/black\n  rev: 1f0c2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b  # frozen: 24.8.0\n"
            "  hooks:\n  - id: black\n"
            "- repo: https://github.com/x/y\n  rev: main\n  hooks:\n  - id: y\n"
            "- repo: local\n  hooks:\n  - id: z\n    entry: z\n"
            "- not a repo\n"
        )
        self.assertEqual(_pinned(_pre_commit(".pre-commit-config.yaml", text)), [("black", "24.8.0")])

    def test_files_that_do_not_parse_pin_nothing(self) -> None:
        self.assertEqual(_pinned(_pre_commit(".pre-commit-config.yaml", "repos: [")), [])
        self.assertEqual(_pinned(_pre_commit(".pre-commit-config.yaml", "- a list")), [])
        self.assertEqual(_pinned(_package_json("package.json", "{")), [])
        self.assertEqual(_pinned(_package_json("package.json", "[]")), [])

    def test_requirements_and_package_json(self) -> None:
        text = "ruff==0.6.9  # lint\ncoverage[toml]==7.6.1\npytest>=8\nmypy==1.*\n"
        self.assertEqual(
            _pinned(_requirements("requirements-dev.txt", text)), [("ruff", "0.6.9"), ("coverage", "7.6.1")]
        )
        manifest = '{"devDependencies": {"eslint": "9.1.0", "tsx": "v4.0.0", "x": 1}, "dependencies": "none"}'
        self.assertEqual(_pinned(_package_json("package.json", manifest)), [("eslint", "9.1.0")])


if __name__ == "__main__":
    unittest.main()
