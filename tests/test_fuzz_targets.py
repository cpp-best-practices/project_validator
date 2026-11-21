"""The repository's own atheris fuzz targets stay importable and total on garbage input."""

from __future__ import annotations

import contextlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import yaml

FUZZ_DIRECTORY = Path(__file__).parent / "fuzz"
CORPUS = FUZZ_DIRECTORY / "corpus"
CRASHES = FUZZ_DIRECTORY / "crashes"
WORKFLOW = FUZZ_DIRECTORY.parent.parent / ".github" / "workflows" / "fuzzing.yml"


def stubbed_atheris() -> mock.MagicMock:
    atheris = mock.MagicMock()
    atheris.instrument_imports.side_effect = contextlib.nullcontext
    return atheris


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"fuzz_target_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replayed_inputs(target: str) -> list[Path]:
    """The committed seeds of `target` and the crash inputs kept from its fixed crashes (`.gitkeep` aside)."""
    folders = (CORPUS / target, CRASHES / target)
    return [path for folder in folders if folder.is_dir() for path in folder.iterdir() if not path.name.startswith(".")]


class FuzzTargetTests(unittest.TestCase):
    def test_every_target_exposes_test_one_input(self) -> None:
        paths = sorted(FUZZ_DIRECTORY.glob("fuzz_*.py"))
        self.assertEqual(len(paths), 6)
        for path in paths:
            with self.subTest(path.name), mock.patch.dict(sys.modules, {"atheris": stubbed_atheris()}):
                module = load_module(path)
                self.assertTrue(callable(module.TestOneInput))
                module.TestOneInput(b"")
                module.TestOneInput(b"{[(" * 50)

    def test_the_json_target_agrees_with_json_loads_on_non_finite_numbers_and_huge_integers(self) -> None:
        with mock.patch.dict(sys.modules, {"atheris": stubbed_atheris()}):
            module = load_module(FUZZ_DIRECTORY / "fuzz_json.py")
        for text in ("NaN", "[NaN, -Infinity]", "9" * 5000, "Infinity"):
            with self.subTest(text=text[:20]):
                module.TestOneInput(text.encode())

    def test_every_seed_and_saved_crash_replays_without_an_error(self) -> None:
        # The seeds and the minimised crash inputs a fixed fuzz crash leaves behind are replayed here, on every OS the
        # unit tests run on: atheris has Linux wheels only, so the fuzzing job alone would never run them elsewhere.
        # A target raises only on a bug (its parser's own errors are caught inside), the rule the fuzzer applies.
        for path in sorted(FUZZ_DIRECTORY.glob("fuzz_*.py")):
            target = path.stem.removeprefix("fuzz_")
            inputs = sorted(replayed_inputs(target))
            with mock.patch.dict(sys.modules, {"atheris": stubbed_atheris()}):
                module = load_module(path)
            self.assertTrue(inputs, target)
            for found in inputs:
                with self.subTest(found.relative_to(FUZZ_DIRECTORY).as_posix()):
                    module.TestOneInput(found.read_bytes())

    def test_each_target_has_a_folder_for_its_crash_inputs(self) -> None:
        for path in sorted(FUZZ_DIRECTORY.glob("fuzz_*.py")):
            with self.subTest(path.name):
                self.assertTrue((CRASHES / path.stem.removeprefix("fuzz_")).is_dir())

    def test_unittest_discovers_nothing_under_tests_fuzz(self) -> None:
        self.assertEqual(unittest.defaultTestLoader.discover(str(FUZZ_DIRECTORY)).countTestCases(), 0)


class FingerprintTests(unittest.TestCase):
    """The CI cache of a target's corpus is keyed on the target and the parser modules it imports."""

    def setUp(self) -> None:
        self.fingerprint = load_module(FUZZ_DIRECTORY / "fingerprint.py")

    def test_a_target_s_modules_are_those_it_imports(self) -> None:
        modules = self.fingerprint.imported_modules(FUZZ_DIRECTORY / "fuzz_json.py")
        self.assertIn("project_validator/text.py", modules)
        self.assertNotIn("project_validator/build_systems/cmake/__init__.py", modules)
        self.assertEqual(modules, sorted(modules))

    def test_the_digest_follows_the_contents_and_names_of_the_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("a = 1\n")
            (root / "b.py").write_text("b = 1\n")
            before = self.fingerprint.digest(root, ["a.py", "b.py"])
            self.assertEqual(before, self.fingerprint.digest(root, ["a.py", "b.py"]))
            self.assertNotEqual(before, self.fingerprint.digest(root, ["a.py"]))
            (root / "b.py").write_text("b = 2\n")
            self.assertNotEqual(before, self.fingerprint.digest(root, ["a.py", "b.py"]))

    def test_the_command_prints_the_target_s_fingerprint(self) -> None:
        completed = subprocess.run(  # noqa: S603 - this interpreter and a script of the repository
            [sys.executable, str(FUZZ_DIRECTORY / "fingerprint.py"), "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertRegex(completed.stdout, r"^[0-9a-f]{16}\n$")


class FuzzWorkflowTests(unittest.TestCase):
    """The fuzzing workflow keeps each target's corpus between runs, pruned, in a cache keyed on its fingerprint."""

    def setUp(self) -> None:
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.job = self.workflow["jobs"]["fuzz"]
        self.scripts = [step.get("run", "") for step in self.job["steps"]]

    def test_every_target_is_fuzzed(self) -> None:
        targets = sorted(path.stem.removeprefix("fuzz_") for path in FUZZ_DIRECTORY.glob("fuzz_*.py"))
        self.assertEqual(sorted(self.job["strategy"]["matrix"]["target"]), targets)

    def test_the_corpus_is_restored_by_target_and_fingerprint_then_pruned_before_it_is_saved(self) -> None:
        uses = [step.get("uses", "").split("@")[0] for step in self.job["steps"]]
        restore, save = uses.index("actions/cache/restore"), uses.index("actions/cache/save")
        merge = next(index for index, script in enumerate(self.scripts) if "-merge=1" in script)
        self.assertLess(restore, merge)
        self.assertLess(merge, save)
        restored = self.job["steps"][restore]["with"]
        self.assertIn("steps.fingerprint.outputs.digest", restored["key"])
        self.assertIn("github.run_id", restored["key"])
        self.assertEqual(
            restored["restore-keys"].splitlines(),
            ["fuzz-${{ matrix.target }}-${{ steps.fingerprint.outputs.digest }}-", "fuzz-${{ matrix.target }}-"],
        )
        self.assertEqual(self.job["steps"][save]["with"]["key"], restored["key"])

    def test_the_committed_seeds_are_always_read(self) -> None:
        fuzzing = [script for script in self.scripts if "-max_total_time" in script]
        self.assertEqual(len(fuzzing), 1)
        self.assertIn("tests/fuzz/corpus/${{ matrix.target }}", fuzzing[0])

    def test_a_weekly_run_fuzzes_for_longer(self) -> None:
        # PyYAML reads the key "on" as True.
        self.assertIn("schedule", self.workflow[True])

    def test_every_target_runs_as_a_program_as_libfuzzer_s_merge_reruns_it(self) -> None:
        for path in sorted(FUZZ_DIRECTORY.glob("fuzz_*.py")):
            with self.subTest(path.name):
                self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"))
                if os.name == "posix":
                    self.assertTrue(os.access(path, os.X_OK))
