"""The browser page (upstream #127): the validator runs in the visitor's browser under Pyodide, on a folder they pick,
and shows its HTML report. `project_validator.web` is what the page calls; the page's files are checked to agree with
it, and with each other."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, ClassVar

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
        for name in ("index.html", "app.js", "worker.js", "github.js"):
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


_READ = r"""
const { parseRepository, readRepository } = require(process.argv[1]);
const tree = [
  { path: "README.md", type: "blob", mode: "100644", size: 6 },
  { path: "src/a b.py", type: "blob", mode: "100644", size: 4 },
  { path: "big.bin", type: "blob", mode: "100644", size: 2000000 },
  { path: "link", type: "blob", mode: "120000", size: 4 },
  { path: "src", type: "tree", mode: "040000" },
];
const asked = [];
let flaky = 1;
global.fetch = async (url, options) => {
  asked.push(url);
  const ok = (body) => ({ ok: true, status: 200, json: async () => body, arrayBuffer: async () => Buffer.from(body) });
  const token = options && options.headers.Authorization === "Bearer t";
  if (url.includes("/commits/")) return token ? ok({ sha: "c0ffee" }) : { ok: false, status: 403 };
  if (url.includes("/git/trees/")) return ok({ tree });
  const raw = url.includes("raw.githubusercontent.com");
  if (raw && url.endsWith("README.md") && flaky-- > 0) return { ok: false, status: 501 };
  if (raw && url.includes("a%20b.py")) return { ok: false, status: 404 };
  return ok(url.includes("README") ? "readme" : "code");
};
(async () => {
  const parsed = ["o/r", "o/r@v1.2", "o/r.git@feature/x", "nope"].map(parseRepository);
  const read = await readRepository(parseRepository("o/r@main"), "t", () => {});
  let limit = "";
  try { await readRepository(parseRepository("o/r"), null, () => {}); } catch (error) { limit = String(error); }
  const files = read.files.map((f) => [f.path, f.size, f.bytes ? Buffer.from(f.bytes).toString() : null]);
  console.log(JSON.stringify({ parsed, root: read.root, commit: read.commit, files, asked, limit }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GitHubTests(unittest.TestCase):
    """The page reads a repository through GitHub's API and raw.githubusercontent.com (github.js, run in node with
    GitHub's answers stubbed)."""

    read: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        node = shutil.which("node") or "node"
        done = subprocess.run(  # noqa: S603 - a fixed script, run by node
            [node, "-e", _READ, str(PAGE / "github.js")], capture_output=True, text=True, check=True, timeout=60
        )
        cls.read = json.loads(done.stdout)

    def test_a_repository_is_written_owner_name_and_a_ref(self) -> None:
        self.assertEqual(
            self.read["parsed"],
            [
                {"owner": "o", "name": "r", "ref": "HEAD"},
                {"owner": "o", "name": "r", "ref": "v1.2"},
                {"owner": "o", "name": "r", "ref": "feature/x"},
                None,
            ],
        )

    def test_every_file_of_the_commit_is_read_but_links_and_large_ones(self) -> None:
        self.assertEqual((self.read["root"], self.read["commit"]), ("r", "c0ffee"))
        self.assertEqual(
            self.read["files"],
            [["r/README.md", 6, "readme"], ["r/src/a b.py", 4, "code"], ["r/big.bin", 2000000, None]],
        )

    def test_a_failed_fetch_is_tried_again_then_read_from_jsdelivr(self) -> None:
        readme = [url for url in self.read["asked"] if url.endswith("README.md")]
        self.assertEqual(readme, ["https://raw.githubusercontent.com/o/r/c0ffee/README.md"] * 2)
        self.assertIn("https://cdn.jsdelivr.net/gh/o/r@c0ffee/src/a%20b.py", self.read["asked"])

    def test_the_api_limit_says_what_to_do(self) -> None:
        self.assertIn("add a token, or try later", self.read["limit"])
