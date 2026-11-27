"""The browser page (upstream #127): the validator runs in the visitor's browser under Pyodide, on a folder they pick,
and shows its HTML report. `project_validator.web` is what the page calls; the page's files are checked to agree with
it, and with each other."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from project_validator import web
from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS
from tests.support import FIXTURES, temp_project

PAGE = Path(__file__).resolve().parent.parent / "web"


class ReportTests(unittest.TestCase):
    def test_a_project_gives_its_exit_code_and_its_html_report(self) -> None:
        code, report = web.report(str(FIXTURES / "well_configured_python"))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(report.startswith("<!DOCTYPE html>"), report[:80])
        self.assertIn("well_configured_python", report)
        self.assertEqual(web.report(str(FIXTURES / "bare_python"))[0], EXIT_FAILURE)

    def test_the_host_is_never_asked(self) -> None:
        """A page has no token and no `origin`: the host settings say they were not read, offline."""
        with temp_project({"main.py": "print(1)\n"}) as root:
            _, report = web.report(str(root))
        self.assertIn("offline", report)

    def test_a_folder_that_is_not_one_is_a_usage_error(self) -> None:
        code, report = web.report("/no/such/folder")
        self.assertEqual((code, report), (2, ""))


class PageTests(unittest.TestCase):
    def test_the_page_its_script_and_its_worker_are_there(self) -> None:
        for name in ("index.html", "app.js", "worker.js"):
            with self.subTest(name=name):
                self.assertTrue((PAGE / name).is_file())

    def test_the_worker_pins_pyodide_and_calls_the_entry_point(self) -> None:
        worker = (PAGE / "worker.js").read_text(encoding="utf-8")
        self.assertRegex(worker, r'const PYODIDE = "https://cdn\.jsdelivr\.net/pyodide/v\d+\.\d+\.\d+/full/";')
        self.assertIn("from project_validator.web import report", worker)
        self.assertIn('loadPackage(["pyyaml", "micropip"])', worker)

    def test_the_page_and_the_worker_speak_the_same_messages(self) -> None:
        sent = set(re.findall(r'postMessage\(\{\s*kind: "(\w+)"', (PAGE / "worker.js").read_text(encoding="utf-8")))
        handled = set(re.findall(r'case "(\w+)":', (PAGE / "app.js").read_text(encoding="utf-8")))
        self.assertEqual(sent, handled)
        self.assertLessEqual({"progress", "report", "failed"}, sent)

    def test_the_site_publishes_the_page_with_the_wheel_it_installs(self) -> None:
        workflow = (PAGE.parent / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("cp web/* _site/app/", workflow)
        self.assertIn("--wheel --outdir _site/app", workflow)
        self.assertIn("> _site/app/wheel.txt", workflow)  # the wheel's name, for the worker
        self.assertIn('fetch("wheel.txt")', (PAGE / "worker.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
