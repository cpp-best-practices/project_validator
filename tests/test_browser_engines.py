"""JavaScript that runs in the browser (upstream #127's question): its platforms are the browser engines CI tests it in,
Chromium, Firefox and WebKit, whatever the OS, as a C++ project's are its compilers. Node versions differ only in what
they support, and the browser code never runs on them. Code that runs in Node is judged by its runtime versions."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Result, Status
from project_validator.ecosystems.javascript.browsers import BROWSER_ENGINES, engine, runs_in_browser
from project_validator.facts import Origin
from project_validator.facts.jobs import Job
from tests.support import make_context, temp_project

PAGE = {
    "web/index.html": '<!doctype html>\n<script type="module" src="app.js"></script>\n',
    "web/app.js": "document.title = 'shop';\n",
}
PLAYWRIGHT = """\
import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'second', use: { browserName: 'firefox' } },
    { name: 'apple', use: { ...devices['Desktop Safari'] } },
  ],
});
"""


def _workflow(*commands: str, runner: str = "ubuntu-latest") -> dict[str, str]:
    steps = "".join(f"      - run: {command}\n" for command in commands)
    return {
        ".github/workflows/ci.yml": (
            f"on: push\njobs:\n  test:\n    runs-on: {runner}\n    steps:\n"
            f"      - uses: actions/setup-node@v4\n        with:\n          node-version: 22\n{steps}"
        )
    }


def _matrix(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        result = platform_matrix.run(make_context(root))
    places = [place for place in result.places if place.ecosystem == "JavaScript"]
    assert len(places) == 1, result  # noqa: S101 - one JavaScript place
    return places[0].result


class BrowserCodeTests(unittest.TestCase):
    def _browser(self, files: Mapping[str, str]) -> bool:
        with temp_project(files) as root:
            return runs_in_browser(make_context(root).facts)

    def test_a_page_that_loads_the_code_runs_it_in_the_browser(self) -> None:
        self.assertTrue(self._browser(PAGE))

    def test_the_script_a_page_loads_is_one_of_the_project_s_own(self) -> None:
        """Relative to the page, or to it or the root for a path from the root (a Vite page's `/src/main.ts`); not a
        build's output, which is not in the repository, nor a template's placeholder (Doxygen's `$relpath^x.js`)."""
        for src, script in (("./app.js?v=2", "web/app.js"), ("/src/main.js", "web/src/main.js"), ("/lib.js", "lib.js")):
            with self.subTest(src=src):
                files = {"web/index.html": f'<script src="{src}"></script>\n', script: "1;\n"}
                self.assertTrue(self._browser(files))
        for src in ("js/out/app.js", "$relpath^jquery.js", "{{ base_url }}/js/base.js"):
            with self.subTest(src=src):
                self.assertFalse(self._browser({"web/index.html": f'<script src="{src}"></script>\n', "a.js": "1;\n"}))

    def test_a_package_for_browsers_says_so(self) -> None:
        for manifest in ('{"name": "a", "browser": "dist/a.js"}', '{"name": "a", "browserslist": ["defaults"]}'):
            with self.subTest(manifest=manifest):
                self.assertTrue(self._browser({"package.json": manifest, "index.js": "export {};\n"}))
        self.assertTrue(self._browser({".browserslistrc": "defaults\n", "index.js": "export {};\n"}))

    def test_code_that_runs_in_node_does_not(self) -> None:
        self.assertFalse(self._browser({"package.json": '{"name": "a", "main": "index.js"}', "index.js": "1;\n"}))
        # A command-line tool runs in Node, whatever page shows it off.
        cli = {**PAGE, "package.json": '{"name": "a", "bin": {"a": "cli.js"}}', "cli.js": "1;\n"}
        self.assertFalse(self._browser(cli))
        # A page that loads only another site's scripts runs none of the project's.
        cdn = {"index.html": '<script src="https://cdn.example.com/x.js"></script>\n', "a.js": "1;\n"}
        self.assertFalse(self._browser(cdn))
        # An example's page, a test's or the docs' runs their own code in the browser, not the product's (express's
        # examples/search/public/index.html and its client.js).
        for page in ("examples/search/public/index.html", "test/fixtures/index.html", "docs/index.html"):
            with self.subTest(page=page):
                script = page.replace("index.html", "client.js")
                example = {page: '<script src="client.js"></script>\n', script: "1;\n", "lib/express.js": "1;\n"}
                self.assertFalse(self._browser(example))
        # A docs site's package, or an example's, says where the site's code runs, not the product's.
        for manifest in ("website/package.json", "examples/app/package.json", "docs/.browserslistrc"):
            with self.subTest(manifest=manifest):
                site = {manifest: '{"browserslist": ["defaults"]}', "package.json": '{"main": "a.js"}', "a.js": "1;\n"}
                self.assertFalse(self._browser(site))
        for manifest in ("{not json", '["browser"]'):  # a package.json that says nothing
            with self.subTest(manifest=manifest):
                self.assertFalse(self._browser({"package.json": manifest, "index.js": "1;\n"}))


class EngineTests(unittest.TestCase):
    def test_browsers_by_their_engines(self) -> None:
        for name, expected in (
            ("chromium", "Chromium"),
            ("ChromeHeadless", "Chromium"),
            ("msedge", "Chromium"),
            ("electron", "Chromium"),
            ("Desktop Chrome", "Chromium"),
            ("Pixel 7", "Chromium"),
            ("firefox", "Firefox"),
            ("FirefoxHeadless", "Firefox"),
            ("webkit", "WebKit"),
            ("Desktop Safari", "WebKit"),
            ("iPhone 15", "WebKit"),
            ("lynx", None),
        ):
            with self.subTest(name=name):
                self.assertEqual(engine(name), expected)


class BrowserMatrixTests(unittest.TestCase):
    def test_the_platforms_of_browser_code_are_the_engines_whatever_the_os(self) -> None:
        files = {**PAGE, "playwright.config.mjs": PLAYWRIGHT, **_workflow("npx playwright test")}
        result = _matrix(files)
        self.assertEqual(result.status, Status.PASS, result.message)
        self.assertIn("CI covers 3 browser engine(s) (Chromium, Firefox, WebKit), whatever the OS", result.message)

    def test_one_engine_is_not_enough(self) -> None:
        result = _matrix({**PAGE, **_workflow("npx playwright test")})  # no configuration: Chromium alone
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("expected at least 2 browser engines (found 1)", result.message)

    def test_the_projects_a_run_picks(self) -> None:
        files = {**PAGE, "playwright.config.mjs": PLAYWRIGHT}
        picked = _matrix({**files, **_workflow("npx playwright test --project=chromium --project second")})
        self.assertIn("2 browser engine(s) (Chromium, Firefox)", picked.message)
        one = _matrix({**files, **_workflow("npx playwright test --project=apple")})
        self.assertIn("1 browser engine(s) (WebKit)", one.message)

    def test_the_runners_browser_options(self) -> None:
        for command, expected in (
            ("npx playwright test --browser=all", "Chromium, Firefox, WebKit"),
            ("npx playwright test --browser firefox", "Firefox"),
            ("npx cypress run --browser firefox", "Firefox"),
            ("npx cypress run", "Chromium"),  # Electron
            ("npx karma start --browsers ChromeHeadless,FirefoxHeadless", "Chromium, Firefox"),
            ("npx wtr --playwright --browsers chromium webkit", "Chromium, WebKit"),
            ("npx wtr --browsers=firefox,webkit --watch", "Firefox, WebKit"),
            ("npx web-test-runner --browsers firefox --playwright", "Firefox"),
            ("npx vitest --browser.name=webkit", "WebKit"),
            ("npx testcafe chrome,firefox tests/", "Chromium, Firefox"),
        ):
            with self.subTest(command=command):
                self.assertIn(f"({expected}), whatever the OS", _matrix({**PAGE, **_workflow(command)}).message)

    def test_karma_reads_its_configuration(self) -> None:
        karma = "module.exports = (config) => config.set({ browsers: ['ChromeHeadless', 'Firefox'] });\n"
        result = _matrix({**PAGE, "karma.conf.js": karma, **_workflow("npx karma start")})
        self.assertIn("(Chromium, Firefox), whatever the OS", result.message)
        bare = _matrix({**PAGE, "karma.conf.js": "module.exports = () => {};\n", **_workflow("npx karma start")})
        self.assertIn("0 browser engine(s) (none)", bare.message)  # no browser it names: none counted

    def test_a_project_of_no_known_engine_counts_none(self) -> None:
        config = "export default { projects: [{ name: 'smoke', use: {} }, { name: 'firefox' }] };\n"
        result = _matrix({**PAGE, "playwright.config.ts": config, **_workflow("npx playwright test")})
        self.assertIn("1 browser engine(s) (Firefox)", result.message)

    def test_a_job_alone_does_not_tell_its_engines(self) -> None:
        """They are read with the project's facts: its commands and the runners' configurations."""
        job = Job(origin=Origin(path="ci.yml"), job="ci.yml#test", name="test", os="linux", compilers=frozenset())
        self.assertEqual(BROWSER_ENGINES.of_job(job), frozenset())

    def test_code_that_runs_in_node_is_judged_by_its_runtime_versions(self) -> None:
        files = {"package.json": '{"name": "a", "main": "index.js"}', "index.js": "1;\n", **_workflow("npm test")}
        self.assertIn("runtime version(s)", _matrix(files).message)


if __name__ == "__main__":
    unittest.main()
