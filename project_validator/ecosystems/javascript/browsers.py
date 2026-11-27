"""JavaScript that runs in the browser: its platforms are the browser engines CI tests it in (Chromium, Firefox,
WebKit), whatever the OS, as a C++ project's are its compilers: each engine is an implementation of its own, and finds
what the others miss. Node versions differ only in what they support, and browser code never runs on them.

The code runs in the browser when a page loads one of its product sources (`<script src>`: not an example's code, a
build's output or a template's placeholder), or the product's package.json says it is for browsers (`browser`,
`browserslist`, or a `.browserslistrc`; not a docs site's), and it installs no command (`bin`), which runs in Node.
Code that runs in Node keeps its runtime versions as its platforms (`RUNTIME_AXIS`).

A job's engines are those its browser test runs drive: Playwright's (`--browser`, `--project`, else every project its
configuration defines, else Chromium), Cypress's (`--browser`, else Electron: Chromium), Karma's (`--browsers`, else its
configuration's), Web Test Runner's, Vitest's browser mode and TestCafe's."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterator

from project_validator.facts import Command, Facts, Origin, Setting, resolved
from project_validator.facts.arguments import option_values, positional, starts_with
from project_validator.facts.axes import ToolchainAxis
from project_validator.facts.jobs import Job
from project_validator.facts.roles import role
from project_validator.facts.settings import SettingsReader

from . import JS_LANGUAGES

CHROMIUM, FIREFOX, WEBKIT = "Chromium", "Firefox", "WebKit"
_ENGINES = (
    (re.compile(r"firefox|gecko", re.IGNORECASE), FIREFOX),
    (re.compile(r"webkit|safari|iphone|ipad", re.IGNORECASE), WEBKIT),
    (re.compile(r"chrom|edge|electron|pixel|galaxy|android", re.IGNORECASE), CHROMIUM),
)


def engine(browser: str) -> str | None:
    """The engine of a browser as test runners name it (`ChromeHeadless`, Playwright's `Desktop Safari` device)."""
    return next((name for pattern, name in _ENGINES if pattern.search(browser)), None)


def _engines(browsers: Iterator[str] | list[str]) -> frozenset[str]:
    return frozenset(found for browser in browsers if (found := engine(browser)) is not None)


TARGETS = "browser targets"
_SCRIPT = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']?(?P<src>[^"'\s>]+)""", re.IGNORECASE)
_REMOTE = re.compile(r"^(?:[a-z]+:|//)", re.IGNORECASE)


def _read_targets(path: str, text: str) -> Iterator[Setting]:
    """What says where the code runs: the project's scripts a page loads, package.json's `browser`, `browserslist`
    and `bin`, a `.browserslistrc`."""
    if path.endswith((".html", ".htm")):
        for found in _SCRIPT.finditer(text):
            if not _REMOTE.match(found["src"]):
                yield _setting(path, "script", found["src"])
    elif path.endswith(".browserslistrc"):
        yield _setting(path, "browserslist", True)
    else:
        try:
            manifest = json.loads(text)
        except json.JSONDecodeError:
            return
        if isinstance(manifest, dict):
            yield from (_setting(path, key, True) for key in ("browser", "browserslist", "bin") if key in manifest)


def _setting(path: str, key: str, value: object) -> Setting:
    return Setting(origin=Origin(path=path), tool=TARGETS, key=key, value=value)


BROWSER_TARGETS = SettingsReader(
    name=TARGETS, files=("*.html", "*.htm", "package.json", ".browserslistrc"), read=_read_targets
)


def _scripts(page: str, src: str) -> tuple[str, ...]:
    """The paths a page's `src` may name: relative to the page, or, from the root (`/src/main.ts`), to the page (a
    Vite page's) or to the project; without a query or a fragment."""
    src = re.split(r"[?#]", src, maxsplit=1)[0]
    directory = posixpath.dirname(page)
    if src.startswith("/"):
        return (posixpath.normpath(posixpath.join(directory, src.lstrip("/"))), posixpath.normpath(src.lstrip("/")))
    return (posixpath.normpath(posixpath.join(directory, src)),)


def runs_in_browser(facts: Facts) -> bool:
    """Whether the project's JavaScript runs in the browser (see the module): a page loads one of its product
    sources (not a build's output, nor a template's placeholder), or the product's package says so (not a docs
    site's, nor an example's)."""
    from project_validator.facts.structure import SourceFile  # structure reads the profiles, this one among them

    found = facts.settings(TARGETS)
    said = {setting.key for setting in found if setting.key != "script" and role(setting.path) == "product"}
    product = {source.path for source in facts.of(SourceFile) if source.role == "product"}
    loaded = any(
        product.intersection(_scripts(setting.path, str(setting.value))) for setting in found if setting.key == "script"
    )
    return (loaded or bool(said & {"browser", "browserslist"})) and "bin" not in said


RUNNER_BROWSERS = "browser test runners"
# A Playwright project: its name, then what it runs in (a device, or a browser by name) before the next project.
_PROJECT = re.compile(r"""\bname\s*:\s*["'](?P<name>[^"']+)["'](?P<use>(?:(?!\bname\s*:).)*)""", re.DOTALL)
_KARMA_BROWSERS = re.compile(r"\bbrowsers\s*:\s*\[(?P<list>[^\]]*)\]")


def _read_runner(path: str, text: str) -> Iterator[Setting]:
    """Playwright's projects, each by name with its engine; Karma's browsers."""
    if "playwright" in path.rsplit("/", 1)[-1]:
        for found in _PROJECT.finditer(text):
            if (engine_of := engine(found["use"]) or engine(found["name"])) is not None:
                yield _runner_setting(path, f"playwright.{found['name']}", engine_of)
    elif listed := _KARMA_BROWSERS.search(text):
        names = re.findall(r"""["']([^"']+)["']""", listed["list"])
        yield from (_runner_setting(path, "karma", name) for name in sorted(_engines(names)))


def _runner_setting(path: str, key: str, value: str) -> Setting:
    return Setting(origin=Origin(path=path), tool=RUNNER_BROWSERS, key=key, value=value)


RUNNER_CONFIGURATION = SettingsReader(
    name=RUNNER_BROWSERS,
    files=("playwright.config.*", "playwright-ct.config.*", "karma.conf.*", "karma.config.*"),
    read=_read_runner,
)


def _words_after(argv: tuple[str, ...], name: str) -> list[str]:
    """The words an option takes, up to the next option (`--browsers chromium webkit`), or after `=`."""
    found: list[str] = []
    for index, word in enumerate(argv):
        if word.startswith(f"{name}="):
            found.append(word.partition("=")[2])
        elif word == name:
            following = argv[index + 1 :]
            found.extend(next((following[:end] for end, w in enumerate(following) if w.startswith("-")), following))
    return [part for word in found for part in word.split(",") if part]


def _playwright(argv: tuple[str, ...], facts: Facts) -> frozenset[str]:
    if browsers := option_values(argv, "--browser"):
        return frozenset((CHROMIUM, FIREFOX, WEBKIT)) if "all" in browsers else _engines(browsers)
    projects = {
        setting.key.removeprefix("playwright."): str(setting.value)
        for setting in facts.settings(RUNNER_BROWSERS)
        if setting.key.startswith("playwright.")
    }
    if picked := option_values(argv, "--project"):
        return frozenset(found for name in picked if (found := projects.get(name) or engine(name)) is not None)
    return frozenset(projects.values()) or frozenset({CHROMIUM})


def _karma(argv: tuple[str, ...], facts: Facts) -> frozenset[str]:
    if browsers := _words_after(argv, "--browsers"):
        return _engines(browsers)
    return frozenset(str(setting.value) for setting in facts.settings(RUNNER_BROWSERS) if setting.key == "karma")


def command_engines(command: Command, facts: Facts) -> frozenset[str]:
    """The engines a command's browser tests run in (see the module)."""
    argv = resolved(command)
    if starts_with(argv, ("playwright", "test")):
        return _playwright(argv, facts)
    if starts_with(argv, ("cypress", "run")):
        return _engines(option_values(argv, "--browser", "-b")) or frozenset({CHROMIUM})
    if starts_with(argv, ("karma", "start")):
        return _karma(argv, facts)
    if starts_with(argv, ("wtr",), ("web-test-runner",)):
        return _engines(_words_after(argv, "--browsers")) or frozenset({CHROMIUM})
    if starts_with(argv, ("vitest",)):
        return _engines(option_values(argv, "--browser", "--browser.name"))
    if starts_with(argv, ("testcafe",)):
        words, _ = positional(argv)
        return _engines(words[0].split(",")) if words else frozenset()
    return frozenset()


def _job_engines(job: Job, facts: Facts) -> frozenset[str]:
    return frozenset().union(*(command_engines(command, facts) for command in facts.where(Command, job=job.job)))


def _no_engines(_job: Job) -> frozenset[str]:
    return frozenset()


BROWSER_ENGINES = ToolchainAxis(
    languages=JS_LANGUAGES,
    noun="browser engine",
    of_job=_no_engines,
    of_job_in=_job_engines,
    operating_systems=False,
    applies=runs_in_browser,
)

__all__ = ["BROWSER_ENGINES", "BROWSER_TARGETS", "RUNNER_CONFIGURATION", "command_engines", "engine", "runs_in_browser"]
