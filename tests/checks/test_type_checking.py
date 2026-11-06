import unittest

from project_validator.checks.type_checking import type_checking
from project_validator.core import Result, Status
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.python import PYTHON, TYPE_CHECKING
from project_validator.ecosystems.rust import RUST
from tests.support import FIXTURES, WELL_CONFIGURED_PYTHON, github_job, make_context, run_as

HINT = TYPE_CHECKING.hint
STRICT_HINT = TYPE_CHECKING.strict_hint


def _ci(*commands: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *commands)


class TypeCheckingTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, type_checking, files, PYTHON)

    def test_applies_to_python_only_of_the_built_in_ecosystems(self) -> None:
        self.assertIn("Python", type_checking.languages)
        for ecosystem in (C_AND_CXX, RUST, GO):
            with self.subTest(ecosystem.label):
                self.assertFalse(ecosystem.languages & type_checking.languages)

    def test_the_well_configured_project_passes_with_the_bonus(self) -> None:
        expected = Result.passed("mypy (pyproject.toml) runs; strict mode bonus: mypy strict = true in pyproject.toml")
        self.assertEqual(self._run(WELL_CONFIGURED_PYTHON), expected)

    def test_compiled_ecosystems_are_skipped(self) -> None:
        self.assertEqual(type_checking.run(make_context(FIXTURES / "well_configured_c_cpp")).status, Status.SKIP)

    def test_fails_when_no_type_checker_runs(self) -> None:
        self.assertEqual(self._run(_ci("pytest")), Result.failed("no type checker runs", HINT))

    def test_any_type_checker_passes_and_suggests_strict_mode(self) -> None:
        cases = {
            "mypy src": "mypy",
            "basedpyright": "pyright",
            "npx pyright": "pyright",
            "pyrefly check": "pyrefly",
            "uvx ty check": "ty",
        }
        for command, checker in cases.items():
            with self.subTest(command):
                self.assertEqual(self._run(_ci(command)), Result.passed(f"{checker} runs", STRICT_HINT))

    def test_ty_must_be_checking(self) -> None:
        self.assertEqual(self._run(_ci("pip install ty")).status, Status.FAIL)

    def test_a_pre_commit_hook_runs_mypy(self) -> None:
        hooks = {".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/pre-commit/mirrors-mypy\n"}
        self.assertEqual(self._run(hooks), Result.passed("mypy runs", STRICT_HINT))

    def test_names_every_checker_that_runs(self) -> None:
        self.assertEqual(self._run(_ci("mypy .", "pyright")), Result.passed("mypy and pyright run", STRICT_HINT))

    def test_warns_when_a_checker_is_configured_but_not_run(self) -> None:
        cases = {
            "mypy.ini": ("[mypy]\n", "mypy"),
            "setup.cfg": ("[mypy]\nwarn_unused_ignores = True\n", "mypy"),
            "pyrightconfig.json": ("{}", "pyright"),
            "pyrefly.toml": ("", "pyrefly"),
            "ty.toml": ("", "ty"),
        }
        for path, (text, checker) in cases.items():
            with self.subTest(path):
                expected = Result.warned(f"{checker} is configured ({path}) but does not run", HINT)
                self.assertEqual(self._run({path: text}), expected)

    def test_pyproject_sections_configure_checkers(self) -> None:
        pyproject = "[project]\nname = 'x'\n\n[tool.basedpyright]\n\n[tool.ty.rules]\n"
        expected = Result.warned(
            "pyright is configured (pyproject.toml) but does not run; "
            "ty is configured (pyproject.toml) but does not run",
            HINT,
        )
        self.assertEqual(self._run({"pyproject.toml": pyproject}), expected)

    def test_strict_mode_is_found_where_it_is_enabled(self) -> None:
        cases = {
            "mypy strict = true in pyproject.toml": {"pyproject.toml": "[tool.mypy]\nstrict = true\n"},
            "mypy strict = true in mypy.ini": {"mypy.ini": "[mypy]\npython_version = 3.13\nstrict = True\n"},
            "mypy strict = true in setup.cfg": {"setup.cfg": "[mypy]\nstrict = 1\n"},
            "pyright typeCheckingMode in pyrightconfig.json": {"pyrightconfig.json": '{"typeCheckingMode": "strict"}'},
            "pyright typeCheckingMode in pyproject.toml": {
                "pyproject.toml": '[tool.basedpyright]\ntypeCheckingMode = "all"\n'
            },
            "mypy --strict": {},
        }
        for where, files in cases.items():
            with self.subTest(where):
                result = self._run({**files, **_ci("mypy --strict src")})
                self.assertEqual(result.status, Status.PASS)
                self.assertTrue(result.message.endswith(f"; strict mode bonus: {where}"), result.message)

    def test_strict_settings_elsewhere_are_not_strict_mode(self) -> None:
        files = {
            "pyproject.toml": "[tool.mypy]\nstrict = false\n",
            "setup.cfg": "[mypy]\nwarn_unused_ignores = True\n\n[other]\nstrict = true\n",
            "pyrightconfig.json": '{"typeCheckingMode": "basic"}',
        }
        result = self._run({**files, **_ci("mypy src")})
        self.assertEqual(result.details, (STRICT_HINT,))
