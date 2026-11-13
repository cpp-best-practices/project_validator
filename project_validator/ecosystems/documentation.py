"""Documentation sites: MkDocs, Sphinx, Docusaurus, mdBook, Hugo and Jekyll, one format each, recognised by content
(the generator's configuration: `mkdocs.yml`, a Sphinx `conf.py`, `docusaurus.config.*`, `book.toml`, `hugo.toml`,
a Jekyll `_config.yml`). Prose itself (Markdown in every repository) makes no documentation site. The site's files are
Markdown, and its configuration is YAML, TOML, Python or JavaScript, judged by their own profiles; what is asked of
the site is that CI builds it (`tests-run`), that the build fails on a warning (`warnings-as-errors`: `mkdocs build
--strict`, `sphinx-build -W`, `onBrokenLinks: 'throw'`, `hugo --panicOnWarning`, `jekyll build --strict_front_matter`;
mdBook has no such switch), that the prose is linted (`static-analysis`: markdownlint, vale), and that the built site
is ignored and never committed (`vcs-ignore`, `committed-artifacts`). Link checking is a check of its own, later."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.expansion import Action
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always, requirement_reader
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, Tool, defined_by, starts, when

MKDOCS, SPHINX, DOCUSAURUS, MDBOOK, HUGO, JEKYLL = "MkDocs", "Sphinx", "Docusaurus", "mdBook", "Hugo", "Jekyll"
GENERATORS = frozenset({MKDOCS, SPHINX, DOCUSAURUS, MDBOOK, HUGO, JEKYLL})


def _only(generator: str) -> frozenset[str]:
    return frozenset({generator})


# --- Recognition: each generator's configuration --------------------------------------------------------------------

_CONFIGURATION = {
    MKDOCS: re.compile(r"(?:^|/)mkdocs\.ya?ml$"),
    SPHINX: re.compile(r"(?:^|/)conf\.py$"),
    DOCUSAURUS: re.compile(r"(?:^|/)docusaurus\.config\.[cm]?[jt]s$"),
    MDBOOK: re.compile(r"(?:^|/)book\.toml$"),
    HUGO: re.compile(r"(?:^|/)hugo\.(?:toml|ya?ml|json)$"),
    JEKYLL: re.compile(r"(?:^|/)_config\.ya?ml$"),
}
# A conf.py is Sphinx's when it sets up Sphinx; a _config.yml is Jekyll's when it says so, or the site has its layouts.
_SPHINX_SETTINGS = re.compile(r"^\s*(?:extensions|html_theme|master_doc|root_doc|project)\s*=", re.MULTILINE)
_JEKYLL_SETTINGS = re.compile(r"jekyll|^\s*(?:theme|remote_theme|markdown|permalink|baseurl):", re.MULTILINE | re.I)
_JEKYLL_DIRECTORIES = ("_posts/", "_layouts/", "_includes/")
# What each generator's configuration is written in: the format or language its file is a source of.
_WRITTEN_IN = {
    MKDOCS: frozenset({"YAML"}),
    SPHINX: frozenset({"Python"}),
    DOCUSAURUS: frozenset({"JavaScript", "TypeScript"}),
    MDBOOK: frozenset({"TOML"}),
    HUGO: frozenset({"TOML", "YAML", "JSON"}),
    JEKYLL: frozenset({"YAML"}),
}


def _configures(project: Project, generator: str, path: str, files: list[str]) -> bool:
    if generator == SPHINX:
        return _SPHINX_SETTINGS.search(project.read_head(path)) is not None
    if generator == JEKYLL:
        base = str(PurePosixPath(path).parent)
        prefix = "" if base == "." else f"{base}/"
        in_site = any(other.startswith(f"{prefix}{name}") for other in files for name in _JEKYLL_DIRECTORIES)
        return in_site or _JEKYLL_SETTINGS.search(project.read_head(path)) is not None
    return True


def documentation_sites(project: Project) -> frozenset[str]:
    """The generators whose sites the project holds, each told by its configuration file."""
    files = project.files()
    return frozenset(
        generator
        for generator, pattern in _CONFIGURATION.items()
        if any(pattern.search(path) and _configures(project, generator, path, files) for path in files)
    )


DOCUMENTATION = Ecosystem(
    label="Documentation site",
    kind="format",
    languages=GENERATORS,
    detect=documentation_sites,
    ci_programs=(
        ("mkdocs",),
        ("sphinx-build",),
        ("sphinx",),
        ("docusaurus",),
        ("mdbook",),
        ("hugo",),
        ("jekyll",),
        ("markdownlint",),
        ("markdownlint-cli2",),
        ("vale",),
    ),
    ci_usage=re.compile(
        r"(?<![\w-])(?:actions-hugo|actions-mdbook|mkdocs-deploy-gh-pages|jekyll-build-pages|sphinx-notes/pages"
        r"|markdownlint-cli2-action|vale-action)\b"
    ),
)


# --- The build: the site's tests ------------------------------------------------------------------------------------


def _site(generator: str, how: str, runs: Callable[[Command, Facts], Run | None]) -> tuple[TestFiles, Tool]:
    """The generator's configuration, as the file that defines its site, and the build that renders it."""
    files = TestFiles(
        name=f"the {generator} site's configuration",
        languages=_only(generator),
        path=_CONFIGURATION[generator],
        written_in=_WRITTEN_IN[generator],
    )
    build = test_runner(
        name=f"{generator} build", languages=_only(generator), how=how, runs=runs, tests=tests_of(files.name)
    )
    return files, build


def _hugo_builds(command: Command, _facts: Facts) -> Run | None:
    """`hugo` alone, or `hugo build`, renders the site; its other subcommands do not."""
    argv = resolved(command)
    if program(argv) != "hugo":
        return None
    subcommand = next((word for word in argv[1:] if not word.startswith("-")), None)
    return tested() if subcommand in (None, "build") else None


MKDOCS_SITE, MKDOCS_BUILD = _site(
    MKDOCS, "mkdocs build --strict", when(starts(("mkdocs", "build"), ("mkdocs", "gh-deploy")), tested)
)
SPHINX_SITE, SPHINX_BUILD = _site(
    SPHINX, "sphinx-build -W docs docs/_build", when(starts(("sphinx-build",), ("sphinx",)), tested)
)
DOCUSAURUS_SITE, DOCUSAURUS_BUILD = _site(
    DOCUSAURUS, "docusaurus build (npm run build)", when(starts(("docusaurus", "build")), tested)
)
MDBOOK_SITE, MDBOOK_BUILD = _site(
    MDBOOK, "mdbook build (and mdbook test)", when(starts(("mdbook", "build"), ("mdbook", "test")), tested)
)
HUGO_SITE, HUGO_BUILD = _site(HUGO, "hugo --minify", _hugo_builds)
JEKYLL_SITE, JEKYLL_BUILD = _site(
    JEKYLL, "jekyll build (bundle exec jekyll build)", when(starts(("jekyll", "build")), tested)
)

MKDOCS_DEPLOY_ACTION = Action(
    name="mhausenblas/mkdocs-deploy-gh-pages", runs=lambda _inputs: (("mkdocs", "gh-deploy", "--force"),)
)
JEKYLL_PAGES_ACTION = Action(name="actions/jekyll-build-pages", runs=lambda _inputs: (("jekyll", "build"),))


def _sphinx_pages(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`sphinx-notes/pages` runs sphinx-build with its `sphinx_build_options`."""
    return (("sphinx-build", *shlex.split(inputs.get("sphinx_build_options", ""))),)


SPHINX_PAGES_ACTION = Action(name="sphinx-notes/pages", runs=_sphinx_pages)


# --- Warnings as errors: the build fails on a warning ---------------------------------------------------------------

ON_BROKEN_LINKS = Requirement(
    name="onBrokenLinks: 'throw' in docusaurus.config", pattern=re.compile(r"onBrokenLinks:\s*['\"]throw['\"]")
)
DOCUSAURUS_SETTINGS = requirement_reader(
    "Docusaurus configuration",
    ("docusaurus.config.js", "docusaurus.config.ts", "docusaurus.config.mjs", "docusaurus.config.cjs"),
    (ON_BROKEN_LINKS,),
)


def _fails_on_warnings(generator: str, requirement: Requirement, hint: str, reads: tuple[str, ...] = ()) -> Practice:
    return Practice(
        name=PracticeName.WARNINGS_AS_ERRORS,
        languages=_only(generator),
        requirements=always(requirement),
        reads=reads,
        words=Wording(kind="warnings as errors", searched="CI configuration", hint=hint),
    )


MKDOCS_STRICT = _fails_on_warnings(
    MKDOCS,
    Requirement(name="mkdocs build --strict", runs=re.compile(r"\bmkdocs\b.*\s(?:--strict|-s)\b"), hints=("mkdocs",)),
    "build with mkdocs build --strict, which fails on a warning (a broken link, a page not in the nav)",
)
SPHINX_STRICT = _fails_on_warnings(
    SPHINX,
    Requirement(
        name="sphinx-build -W",
        runs=re.compile(r"\bsphinx(?:-build)?\b.*\s(?:-[a-zA-Z]*W[a-zA-Z]*|--fail-on-warning)\b"),
        hints=("sphinx",),
    ),
    "build with sphinx-build -W (--fail-on-warning), which fails on a warning",
)
DOCUSAURUS_STRICT = _fails_on_warnings(
    DOCUSAURUS,
    ON_BROKEN_LINKS,
    "set onBrokenLinks: 'throw' (and onBrokenMarkdownLinks) in docusaurus.config: a broken link fails the build",
    reads=(DOCUSAURUS_SETTINGS.name,),
)
HUGO_STRICT = _fails_on_warnings(
    HUGO,
    Requirement(name="hugo --panicOnWarning", runs=re.compile(r"\bhugo\b.*\s--panicOnWarning\b"), hints=("hugo",)),
    "build with hugo --panicOnWarning, which fails on a warning",
)
JEKYLL_STRICT = _fails_on_warnings(
    JEKYLL,
    Requirement(
        name="jekyll build --strict_front_matter",
        runs=re.compile(r"\bjekyll\b.*\s--strict_front_matter\b"),
        hints=("jekyll",),
    ),
    "build with jekyll build --strict_front_matter, which fails on a page whose front matter does not parse",
)


# --- Prose linters --------------------------------------------------------------------------------------------------

MARKDOWNLINT_SETTINGS = file_reader(
    "markdownlint",
    (
        ".markdownlint.yaml",
        ".markdownlint.yml",
        ".markdownlint.json",
        ".markdownlint.jsonc",
        ".markdownlint-cli2.yaml",
        ".markdownlint-cli2.jsonc",
        ".markdownlint-cli2.cjs",
        ".markdownlint-cli2.mjs",
    ),
)
MARKDOWNLINT = analyzer(
    name="markdownlint",
    languages=GENERATORS,
    how="markdownlint-cli2 (or DavidAnson/markdownlint-cli2-action)",
    analyses=when(starts(("markdownlint",), ("markdownlint-cli2",)), analysed),
    rules=defined_by(files=(MARKDOWNLINT_SETTINGS.name,)),
)
VALE_SETTINGS = file_reader("vale", (".vale.ini", "_vale.ini", "vale.ini"))
VALE = analyzer(
    name="vale",
    languages=GENERATORS,
    how="vale docs (or errata-ai/vale-action)",
    analyses=when(starts(("vale",)), analysed),
    rules=defined_by(files=(VALE_SETTINGS.name,), default=False),
)
MARKDOWNLINT_ACTION = Action(
    name="DavidAnson/markdownlint-cli2-action",
    runs=lambda inputs: (("markdownlint-cli2", *shlex.split(inputs.get("globs", "**/*.md"))),),
)
VALE_ACTION = Action(name="errata-ai/vale-action", runs=lambda inputs: (("vale", inputs.get("files", ".")),))


# --- The built site ---------------------------------------------------------------------------------------------------


def _built_site(generator: str, *names: str) -> tuple[BuildOutput, ...]:
    return tuple(
        BuildOutput(
            languages=_only(generator),
            name=f"the {generator} site {name}/",
            globs=ignored_at_top_level(re.escape(name)),
            paths=directories(name),
            hint=f"consider ignoring {name}/",
            artifacts=(f"{name}/",),
        )
        for name in names
    )


MKDOCS_OUTPUT = _built_site(MKDOCS, "site")
SPHINX_OUTPUT = _built_site(SPHINX, "_build")
DOCUSAURUS_OUTPUT = _built_site(DOCUSAURUS, "build", ".docusaurus")
MDBOOK_OUTPUT = _built_site(MDBOOK, "book")
HUGO_OUTPUT = _built_site(HUGO, "public")
JEKYLL_OUTPUT = _built_site(JEKYLL, "_site", ".jekyll-cache")
