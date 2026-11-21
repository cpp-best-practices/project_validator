"""tests/conftest.py: under `pytest -x`, as mutmut runs the tests, a test stops at its first failing subtest."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MATRIX_TEST = """
import unittest


class Matrix(unittest.TestCase):
    def test_every_layout(self) -> None:
        for layout in range(4):
            with self.subTest(layout=layout):
                print(f"layout {layout}", flush=True)
                self.assertNotEqual(layout, 1)
"""


@unittest.skipUnless(importlib.util.find_spec("pytest"), "only pytest reads tests/conftest.py")
class ExitFirstTests(unittest.TestCase):
    def layouts_run(self, *options: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).with_name("conftest.py"), root / "conftest.py")
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            (root / "test_matrix.py").write_text(MATRIX_TEST, encoding="utf-8")
            command = [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", *options]
            completed = subprocess.run(  # noqa: S603 - this interpreter running pytest
                command, cwd=root, capture_output=True, text=True, check=False
            )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        # pytest prints each subtest's progress letter on the line the next subtest's output starts.
        return re.findall(r"layout \d", completed.stdout)

    def test_exit_first_stops_a_test_at_its_first_failing_subtest(self) -> None:
        # A killed mutant would otherwise pay for every remaining layout of the whole-matrix tests.
        self.assertEqual(self.layouts_run("-x"), ["layout 0", "layout 1"])

    def test_without_it_every_subtest_runs(self) -> None:
        self.assertEqual(self.layouts_run(), ["layout 0", "layout 1", "layout 2", "layout 3"])
