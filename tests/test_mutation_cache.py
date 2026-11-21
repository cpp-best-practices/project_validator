"""The mutation job's cache: verdicts carried between runs, reset where a function or the tests covering it changed."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from tests.mutation_cache import affected_tests, merged_verdicts, reset_functions, restore, save, survivors

TESTS = {
    "tests/__init__.py": "",
    "tests/support.py": "from tests.deeper import helper\n",
    "tests/deeper.py": "def helper(): ...\n",
    "tests/test_a.py": "from tests.support import x\nSNAPSHOTS = 'snapshots'\n",
    "tests/test_b.py": "import tests.deeper\n",
    "tests/test_c.py": "README = 'README.md'\n",
    "tests/checks/test_d.py": "FIXTURES = 'fixtures'\n",
}


def _tree(files: dict[str, str]) -> tempfile.TemporaryDirectory[str]:
    directory = tempfile.TemporaryDirectory()
    for path, text in files.items():
        (Path(directory.name) / path).parent.mkdir(parents=True, exist_ok=True)
        (Path(directory.name) / path).write_text(text, encoding="utf-8")
    return directory


class AffectedTestsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = _tree(TESTS)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def affected(self, *changed: str) -> set[str] | None:
        return affected_tests(changed, self.root)

    def test_a_changed_test_module_is_affected(self) -> None:
        self.assertEqual(self.affected("tests/checks/test_d.py"), {"tests/checks/test_d.py"})

    def test_a_changed_helper_affects_every_test_module_that_imports_it_however_indirectly(self) -> None:
        self.assertEqual(self.affected("tests/deeper.py"), {"tests/test_a.py", "tests/test_b.py"})
        self.assertEqual(self.affected("tests/support.py"), {"tests/test_a.py"})

    def test_the_validator_s_own_modules_are_left_to_mutmut_s_function_hashes(self) -> None:
        self.assertEqual(self.affected("project_validator/core.py"), set())

    def test_a_changed_data_file_of_the_validator_affects_everything(self) -> None:
        self.assertIsNone(self.affected("project_validator/views/assets/site.css"))

    def test_test_data_affects_the_test_modules_that_name_its_folder(self) -> None:
        self.assertEqual(self.affected("tests/snapshots/bare_c.json"), {"tests/test_a.py"})
        self.assertEqual(self.affected("tests/fixtures/bare_c/main.c"), {"tests/checks/test_d.py"})

    def test_test_data_no_test_module_names_affects_everything(self) -> None:
        self.assertIsNone(self.affected("tests/layouts/x.json"))

    def test_another_file_affects_the_test_modules_that_name_it_and_otherwise_nothing(self) -> None:
        self.assertEqual(self.affected("README.md"), {"tests/test_c.py"})
        self.assertEqual(self.affected("LICENSE.txt"), set())

    def test_a_changed_conftest_affects_everything_since_pytest_loads_it_for_every_test(self) -> None:
        self.assertIsNone(self.affected("tests/conftest.py"))

    def test_a_deleted_test_module_affects_nothing_it_no_longer_runs(self) -> None:
        self.assertEqual(self.affected("tests/test_gone.py"), set())


class ResetFunctionsTests(unittest.TestCase):
    COVERAGE: ClassVar[dict[str, list[str]]] = {
        "project_validator.a.x_f": ["tests/test_a.py::A::test_one", "tests/test_b.py::B::test_two"],
        "project_validator.a.x_g": ["tests/test_b.py::B::test_three"],
        "project_validator.b.x_h": ["tests/checks/test_d.py::D::test_four"],
    }

    def test_the_functions_a_changed_test_module_covers_are_reset(self) -> None:
        self.assertEqual(reset_functions({"tests/test_a.py"}, self.COVERAGE), {"project_validator.a.x_f"})
        self.assertEqual(
            reset_functions({"tests/test_b.py"}, self.COVERAGE), {"project_validator.a.x_f", "project_validator.a.x_g"}
        )

    def test_everything_stays_everything(self) -> None:
        self.assertIsNone(reset_functions(None, self.COVERAGE))


def _meta(hashes: dict[str, str], verdicts: dict[str, int | None]) -> dict[str, object]:
    return {
        "exit_code_by_key": verdicts,
        "hash_by_function_name": hashes,
        "type_check_error_by_key": {},
        "durations_by_key": {key: 1.0 for key, verdict in verdicts.items() if verdict is not None},
        "estimated_durations_by_key": {},
    }


CACHED = _meta(
    {"x_f": "1", "x_g": "1", "xǁKǁm": "1"},
    {
        "project_validator.a.x_f__mutmut_1": 0,
        "project_validator.a.x_g__mutmut_1": 1,
        "project_validator.a.xǁKǁm__mutmut_1": 0,
    },
)
FRESH = _meta(
    {"x_f": "1", "x_g": "2", "xǁKǁm": "1", "x_new": "1"},
    {
        "project_validator.a.x_f__mutmut_1": None,
        "project_validator.a.x_f__mutmut_2": None,
        "project_validator.a.x_g__mutmut_1": None,
        "project_validator.a.xǁKǁm__mutmut_1": None,
        "project_validator.a.x_new__mutmut_1": None,
    },
)


class MergedVerdictsTests(unittest.TestCase):
    def test_a_verdict_is_kept_only_while_its_function_is_unchanged_and_not_reset(self) -> None:
        merged = merged_verdicts(FRESH, CACHED, reset=set())
        self.assertEqual(
            merged["exit_code_by_key"],
            {
                "project_validator.a.x_f__mutmut_1": 0,
                "project_validator.a.x_f__mutmut_2": None,
                "project_validator.a.x_g__mutmut_1": None,
                "project_validator.a.xǁKǁm__mutmut_1": 0,
                "project_validator.a.x_new__mutmut_1": None,
            },
        )
        self.assertEqual(merged["hash_by_function_name"], FRESH["hash_by_function_name"])
        self.assertEqual(
            merged["durations_by_key"],
            {"project_validator.a.x_f__mutmut_1": 1.0, "project_validator.a.xǁKǁm__mutmut_1": 1.0},
        )

    def test_a_reset_function_loses_its_verdicts(self) -> None:
        merged = merged_verdicts(FRESH, CACHED, reset={"project_validator.a.xǁKǁm"})
        self.assertIsNone(merged["exit_code_by_key"]["project_validator.a.xǁKǁm__mutmut_1"])
        self.assertEqual(merged["exit_code_by_key"]["project_validator.a.x_f__mutmut_1"], 0)

    def test_resetting_everything_keeps_nothing(self) -> None:
        merged = merged_verdicts(FRESH, CACHED, reset=None)
        self.assertEqual(set(merged["exit_code_by_key"].values()), {None})


STATS = {"tests_by_mangled_function_name": {"project_validator.a.x_f": ["tests/test_a.py::A::test_one"]}}


class SaveAndRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = _tree({**TESTS, "mutants/project_validator/a.py.meta": json.dumps(CACHED)})
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "mutants" / "mutmut-stats.json").write_text(json.dumps(STATS), encoding="utf-8")

    def write_fresh(self) -> None:
        (self.root / "mutants" / "project_validator" / "a.py.meta").write_text(json.dumps(FRESH), encoding="utf-8")
        (self.root / "mutants" / "mutmut-stats.json").unlink()

    def restored(self, changed: list[str] | None) -> dict[str, int | None]:
        cache = self.root / "cache"
        save(self.root / "mutants", cache, commit="abc")
        self.assertEqual((cache / "commit").read_text(encoding="utf-8"), "abc\n")
        self.write_fresh()
        restore(cache, self.root / "mutants", changed=changed, root=self.root)
        self.assertEqual(json.loads((self.root / "mutants" / "mutmut-stats.json").read_text(encoding="utf-8")), STATS)
        meta = json.loads((self.root / "mutants" / "project_validator" / "a.py.meta").read_text(encoding="utf-8"))
        verdicts: dict[str, int | None] = meta["exit_code_by_key"]
        return verdicts

    def test_an_unchanged_function_keeps_its_verdicts(self) -> None:
        self.assertEqual(self.restored(changed=[])["project_validator.a.x_f__mutmut_1"], 0)

    def test_a_function_whose_tests_changed_is_tested_again(self) -> None:
        self.assertIsNone(self.restored(changed=["tests/test_a.py"])["project_validator.a.x_f__mutmut_1"])
        self.assertEqual(self.restored(changed=["tests/test_a.py"])["project_validator.a.xǁKǁm__mutmut_1"], 0)

    def test_an_unknown_history_tests_everything_again(self) -> None:
        self.assertEqual(set(self.restored(changed=None).values()), {None})

    def test_a_change_to_how_the_tests_run_restores_nothing(self) -> None:
        for path in ("pyproject.toml", ".github/requirements/mutation.txt"):
            with self.subTest(path):
                cache = self.root / "cache"
                save(self.root / "mutants", cache, commit="abc")
                self.write_fresh()
                self.assertIsNone(restore(cache, self.root / "mutants", changed=[path], root=self.root))
                self.assertFalse((self.root / "mutants" / "mutmut-stats.json").exists())
                meta = json.loads((self.root / "mutants" / "project_validator" / "a.py.meta").read_text("utf-8"))
                self.assertEqual(meta, FRESH)
                (self.root / "mutants" / "project_validator" / "a.py.meta").write_text(json.dumps(CACHED), "utf-8")
                (self.root / "mutants" / "mutmut-stats.json").write_text(json.dumps(STATS), encoding="utf-8")

    def test_an_empty_cache_restores_nothing(self) -> None:
        self.write_fresh()
        restore(self.root / "no-cache", self.root / "mutants", changed=[], root=self.root)
        self.assertFalse((self.root / "mutants" / "mutmut-stats.json").exists())


class SurvivorsTests(unittest.TestCase):
    def test_only_the_survivors_of_the_mutated_functions_are_reported(self) -> None:
        results = [
            "    project_validator.a.x_f__mutmut_1: survived",
            "    project_validator.a.x_old__mutmut_1: survived",
            "    project_validator.a.xǁKǁm__mutmut_2: survived",
        ]
        self.assertEqual(
            survivors(results, ["project_validator.a.x_f*", "project_validator.a.xǁKǁm*"]),
            ["    project_validator.a.x_f__mutmut_1: survived", "    project_validator.a.xǁKǁm__mutmut_2: survived"],
        )


class CommandTests(unittest.TestCase):
    def test_restore_resets_everything_when_the_cached_commit_is_not_in_the_history(self) -> None:
        with _tree({"mutants/project_validator/a.py.meta": json.dumps(FRESH)}) as directory:
            root = Path(directory)
            cache = root / "cache"
            (cache / "meta" / "project_validator").mkdir(parents=True)
            (cache / "meta" / "project_validator" / "a.py.meta").write_text(json.dumps(CACHED), encoding="utf-8")
            (cache / "mutmut-stats.json").write_text(json.dumps(STATS), encoding="utf-8")
            (cache / "commit").write_text("0" * 40 + "\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607 - git from PATH
            command = [sys.executable, str(Path(__file__).parent / "mutation_cache.py"), "restore", str(cache)]
            completed = subprocess.run(  # noqa: S603 - this interpreter and a script of the repository
                command, cwd=root, capture_output=True, text=True, check=True
            )
            self.assertIn("testing every mutant again", completed.stdout)
            meta = json.loads((root / "mutants" / "project_validator" / "a.py.meta").read_text(encoding="utf-8"))
            self.assertEqual(set(meta["exit_code_by_key"].values()), {None})
