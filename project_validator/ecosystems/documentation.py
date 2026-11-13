"""Documentation sites: MkDocs, Sphinx, Docusaurus, mdBook, Hugo and Jekyll, one format each, recognised by content
(the generator's configuration: `mkdocs.yml`, a Sphinx `conf.py`, `docusaurus.config.*`, `book.toml`, `hugo.toml`,
a Jekyll `_config.yml`). Prose itself (Markdown in every repository) makes no documentation site. The site's files are
Markdown, and its configuration is YAML, TOML, Python or JavaScript, judged by their own profiles; what is asked of
the site is that CI builds it (`tests-run`), that the build fails on a warning (`warnings-as-errors`: `mkdocs build
--strict`, `sphinx-build -W`, `onBrokenLinks: 'throw'`, `hugo --panicOnWarning`, `jekyll build --strict_front_matter`;
mdBook has no such switch), that the prose is linted (`static-analysis`: markdownlint, vale), and that the built site
is ignored and never committed (`vcs-ignore`, `committed-artifacts`), and that CI checks the site's links and fails
on a broken one (`link-check`: lychee, Sphinx's `linkcheck` builder, markdown-link-check, mdbook-linkcheck, MkDocs'
htmlproofer plugin, linkinator, muffet, htmltest, HTMLProofer, LinkChecker; a scheduled run counts)."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.expansion import Action
from project_validator.facts.links import link_checker, links_checked
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always, requirement_reader
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
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
        ("lychee",),
        ("markdown-link-check",),
        ("mdbook-linkcheck",),
        ("linkinator",),
        ("muffet",),
        ("htmltest",),
        ("htmlproofer",),
        ("linkchecker",),
    ),
    ci_usage=re.compile(
        r"(?<![\w-])(?:actions-hugo|actions-mdbook|mkdocs-deploy-gh-pages|jekyll-build-pages|sphinx-notes/pages"
        r"|markdownlint-cli2-action|vale-action|lychee-action|github-action-markdown-link-check)\b"
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


# --- Link checking --------------------------------------------------------------------------------------------------


def _link_checker(name: str, how: str, *prefixes: tuple[str, ...]) -> Tool:
    """A link checker any site's CI may run, told by its program."""
    return link_checker(name=name, languages=GENERATORS, how=how, checks=when(starts(*prefixes), links_checked))


def _lychee(command: Command, _facts: Facts) -> Run | None:
    """lychee checks the links of the files it is given and fails on a broken one; `--dump` only lists them."""
    argv = resolved(command)
    if program(argv) != "lychee" or has_option(argv, "--dump", "--dump-inputs"):
        return None
    return links_checked()


LYCHEE = link_checker(
    name="lychee",
    languages=GENERATORS,
    how="lychee --no-progress 'docs/**/*.md' (or lycheeverse/lychee-action)",
    checks=_lychee,
)
MARKDOWN_LINK_CHECK = _link_checker(
    "markdown-link-check",
    "markdown-link-check docs/*.md (or gaurav-nelson/github-action-markdown-link-check)",
    ("markdown-link-check",),
)
LINKINATOR = _link_checker("linkinator", "linkinator site --recurse", ("linkinator",))
MUFFET = _link_checker("muffet", "muffet http://localhost:8000 (the served site)", ("muffet",))
HTMLTEST = _link_checker("htmltest", "htmltest site", ("htmltest",))
HTMLPROOFER = _link_checker("HTMLProofer", "htmlproofer ./_site", ("htmlproofer",), ("html-proofer",))
LINKCHECKER = _link_checker("LinkChecker", "linkchecker site/index.html", ("linkchecker",))


def _sphinx_linkcheck(command: Command, _facts: Facts) -> Run | None:
    """Sphinx's `linkcheck` builder (`sphinx-build -b linkcheck`, `-M linkcheck`) checks the links of the sources;
    `make linkcheck` runs it through the Makefile sphinx-quickstart writes (a pattern rule, which the Make reader does
    not follow), so the target is taken at its word."""
    argv = resolved(command)
    if program(argv) in ("sphinx-build", "sphinx") and "linkcheck" in option_values(argv, "-b", "-M", "--builder"):
        return links_checked()
    return links_checked() if program(argv) == "make" and "linkcheck" in argv[1:] else None


SPHINX_LINKCHECK = link_checker(
    name="sphinx linkcheck",
    languages=_only(SPHINX),
    how="sphinx-build -b linkcheck docs docs/_build/linkcheck",
    checks=_sphinx_linkcheck,
)

# mdBook runs mdbook-linkcheck as a backend when book.toml has an `[output.linkcheck]` table; the backend alone checks
# too. MkDocs checks links with the htmlproofer plugin named in mkdocs.yml.
MDBOOK_SETTINGS = SettingsReader(
    name="mdbook",
    files=("book.toml",),
    read=lambda path, text: matched_settings(
        "mdbook", path, text, {"linkcheck": (re.compile(r"^\[output\.linkcheck\]", re.MULTILINE), True)}
    ),
)
MKDOCS_PLUGINS = SettingsReader(
    name="mkdocs plugins",
    files=("mkdocs.yml", "mkdocs.yaml"),
    read=lambda path, text: matched_settings(
        "mkdocs",
        path,
        text,
        {"htmlproofer plugin": (re.compile(r"^\s*-\s*htmlproofer\b|^\s*htmlproofer:", re.M), True)},
    ),
)


def _with_setting(build: Callable[[Command], bool], tool: str, key: str) -> Callable[[Command, Facts], Run | None]:
    """A build that checks links when the generator's configuration turns the checker on."""

    def claims(command: Command, facts: Facts) -> Run | None:
        if not build(command):
            return None
        read = facts.where(Setting, tool=tool, key=key)
        return links_checked(read=read) if read else None

    return claims


def _mdbook_linkcheck(command: Command, facts: Facts) -> Run | None:
    if starts(("mdbook-linkcheck",))(command):
        return links_checked()
    return _with_setting(starts(("mdbook", "build"), ("mdbook", "test")), "mdbook", "linkcheck")(command, facts)


MDBOOK_LINKCHECK = link_checker(
    name="mdbook-linkcheck",
    languages=_only(MDBOOK),
    how="mdbook build with [output.linkcheck] in book.toml (mdbook-linkcheck installed)",
    checks=_mdbook_linkcheck,
    reads=(MDBOOK_SETTINGS.name,),
)
MKDOCS_HTMLPROOFER = link_checker(
    name="mkdocs-htmlproofer-plugin",
    languages=_only(MKDOCS),
    how="mkdocs build with htmlproofer in mkdocs.yml's plugins",
    checks=_with_setting(starts(("mkdocs", "build"), ("mkdocs", "gh-deploy")), "mkdocs", "htmlproofer plugin"),
    reads=(MKDOCS_PLUGINS.name,),
)


def _lychee_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`lycheeverse/lychee-action` runs lychee with its `args` (the Markdown, HTML and reStructuredText files by
    default) and fails the job on a broken link unless `fail` is false, when it only reports."""
    if inputs.get("fail", "true").strip().lower() == "false":
        return ()
    args = inputs.get("args", "--verbose --no-progress './**/*.md' './**/*.html' './**/*.rst'")
    return (("lychee", *shlex.split(args)),)


def _markdown_link_check_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    return (("markdown-link-check", inputs.get("folder-path", ".")),)


LYCHEE_ACTION = Action(name="lycheeverse/lychee-action", runs=_lychee_action)
MARKDOWN_LINK_CHECK_ACTION = Action(
    name="gaurav-nelson/github-action-markdown-link-check", runs=_markdown_link_check_action
)
MARKDOWN_LINK_CHECK_ACTION_FORK = Action(
    name="tcort/github-action-markdown-link-check", runs=_markdown_link_check_action
)


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
