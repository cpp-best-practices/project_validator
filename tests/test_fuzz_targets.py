"""The repository's own atheris fuzz targets stay importable and total on garbage input."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

FUZZ_DIRECTORY = Path(__file__).parent / "fuzz"
CORPUS = FUZZ_DIRECTORY / "corpus"
CRASHES = FUZZ_DIRECTORY / "crashes"


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
