"""Starting a built-in ecosystem with the scaffold."""

import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from project_validator.ecosystems import Ecosystem
from project_validator.scaffold import main, scaffold

ROOT = Path(__file__).parent.parent


class ScaffoldTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(ROOT / "tests/fixtures/well_configured_go", self.root / "tests/fixtures/well_configured_go")

    def test_writes_what_the_contract_asks_for(self) -> None:
        written = {
            path.relative_to(self.root).as_posix() for path in scaffold(self.root, "nim", "Nim", [".nim", ".nims"])
        }
        self.assertLessEqual(
            {
                "project_validator/ecosystems/nim/__init__.py",
                "project_validator/ecosystems/nim/tools.py",
                "project_validator/ecosystems/nim/practices.py",
                "tests/layouts/nim.py",
                "docs/ecosystems/nim.md",
                "tests/fixtures/bare_nim/src/main.nim",
                "tests/fixtures/well_configured_nim/LICENSE",
                "tests/fixtures/well_configured_nim/.github/workflows/ci-lint.yml",
            },
            written,
        )
        spec = importlib.util.spec_from_file_location(
            "scaffolded_nim", self.root / "project_validator/ecosystems/nim/__init__.py"
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        self.assertIsInstance(module.NIM, Ecosystem)
        self.assertEqual(module.NIM.source_suffixes, {".nim": "Nim", ".nims": "Nim"})

    def test_the_toolchain_is_guessed_from_the_module_name(self) -> None:
        """A setup action, its version input and a container image, named after the module: to be checked."""
        scaffold(self.root, "nim", "Nim", [".nim"])
        spec = importlib.util.spec_from_file_location(
            "scaffolded_nim_toolchain", self.root / "project_validator/ecosystems/nim/__init__.py"
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        self.assertTrue(module.NIM.used_by("uses: jiro4989/setup-nim-action@v2\nwith:\n  nim-version: 2.0.8"))
        [named] = (found for found in module.NIM.toolchain.versions if found.search("nim-version: 2.0.8"))
        self.assertEqual(named.search("nim-version: 2.0.8")[1], "2.0.8")
        self.assertTrue(module.NIM.used_by("image: nim:2.0"))
        self.assertFalse(module.NIM.used_by("echo nim"))
        self.assertTrue((self.root / "docs/ecosystems/nim.md").read_text(encoding="utf-8").startswith("# Nim\n"))

    def test_nothing_is_overwritten_and_names_are_checked(self) -> None:
        scaffold(self.root, "nim", "Nim", [".nim"])
        with self.assertRaises(FileExistsError):
            scaffold(self.root, "nim", "Nim", [".nim"])
        for module, suffixes in (("Nim", [".nim"]), ("nim", ["nim"]), ("nim", [])):
            with self.subTest(module=module, suffixes=suffixes), self.assertRaises(ValueError):
                scaffold(self.root, module, "Nim", suffixes)

    def test_the_command_line(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["nim", "Nim", ".nim", "--root", str(self.root)]), 0)
            self.assertEqual(main(["nim", "Nim", ".nim", "--root", str(self.root)]), 2)
        self.assertIn("tests/layouts/nim.py", out.getvalue())
        self.assertIn("already there", err.getvalue())
