"""The documentation site CI publishes to GitHub Pages: the README, the pages under docs/ and the generated support
matrix, rendered to HTML, each page saying which commit of which branch it was built from.

    python tests/build_site.py OUTPUT [--repository OWNER/NAME] [--ref BRANCH] [--revision SHA]

The site mirrors the repository: README.md becomes index.html, docs/<page>.md becomes docs/<page>.html, and
docs/ecosystems/ gets an index of the ecosystem pages; docs/support-matrix.html is generated from the registry, as
`--support-matrix` prints it. A link to another page is rewritten to that page; a link to anything else in the
repository points at it on GitHub at the built revision, so every link resolves.
"""

import argparse
import html
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import markdown

from project_validator.plugins import discover
from project_validator.support_matrix import render, support_matrix

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = ("tables", "fenced_code", "toc")  # toc gives headings the ids GitHub gives them, for `#anchor` links
NAVIGATION = (
    ("index.html", "Overview"),
    ("docs/architecture.html", "Architecture"),
    ("docs/ecosystems/index.html", "Ecosystems"),
    ("docs/support-matrix.html", "Support matrix"),
)
_LINK = re.compile(r"\]\((?P<target>[^)\s]+)(?P<title>\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)
STYLE = """\
body { max-width: 60rem; margin: 0 auto; padding: 0 1.5rem 3rem; font: 16px/1.5 system-ui, sans-serif; color: #222; }
header { display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; align-items: baseline; padding: 1rem 0; }
header { border-bottom: 1px solid #ddd; }
header nav a { margin-right: 1rem; }
header .built { margin-left: auto; font-size: 0.875rem; color: #555; }
table { border-collapse: collapse; display: block; overflow-x: auto; font-size: 0.9375rem; }
th, td { border: 1px solid #ccc; padding: 0.25rem 0.5rem; text-align: left; vertical-align: top; }
th { background: #f3f3f3; }
pre { background: #f6f8fa; padding: 0.75rem 1rem; overflow-x: auto; }
code { font-size: 0.9375em; }
a { color: #0550ae; }
"""
TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - project_validator</title>
<link rel="stylesheet" href="{to_root}style.css">
</head>
<body>
<header>
<nav>{navigation}</nav>
<span class="built">Built from <code>{ref}</code> at <a href="{commit_url}">{short}</a> on {date}</span>
</header>
<main>
{body}
</main>
</body>
</html>
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Site:
    """Where the site is built from: the repository on GitHub, and the branch and commit the pages reflect."""

    repository: str
    ref: str
    revision: str

    @property
    def commit_url(self) -> str:
        return f"https://github.com/{self.repository}/commit/{self.revision}"

    def file_url(self, path: str, directory: bool) -> str:
        kind = "tree" if directory else "blob"
        return f"https://github.com/{self.repository}/{kind}/{self.revision}/{path}"


def title_of(source: str) -> str:
    """The page's first heading, without its code marks."""
    found = _HEADING.search(source)
    return found.group("title").replace("`", "") if found else "project_validator"


def _html_path(markdown_path: str) -> str:
    return "index.html" if markdown_path == "README.md" else markdown_path.removesuffix(".md") + ".html"


def _ecosystems_index(ecosystem_pages: dict[str, str]) -> str:
    """A page listing the ecosystem pages by their titles."""
    entries = sorted((title_of(source), posixpath.basename(path)) for path, source in ecosystem_pages.items())
    lines = [f"- [{title}]({name})" for title, name in entries]
    return "# Ecosystems\n\nThe ecosystems the validator recognises, and what each check accepts for each.\n\n" + (
        "\n".join(lines) + "\n"
    )


def pages(root: Path) -> dict[str, str]:
    """The site's pages: Markdown source by site path (`index.html`, `docs/<page>.html`)."""
    sources = {"README.md": (root / "README.md").read_text(encoding="utf-8")}
    for path in sorted((root / "docs").rglob("*.md")):
        sources[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    ecosystems = {path: source for path, source in sources.items() if path.startswith("docs/ecosystems/")}
    sources["docs/ecosystems/index.md"] = _ecosystems_index(ecosystems)
    sources["docs/support-matrix.md"] = render(support_matrix(discover().checks))
    return {_html_path(path): source for path, source in sources.items()}


def rewrite_links(source: str, page: str, site_pages: set[str], site: Site, root: Path) -> str:
    """Point the page's relative links at the site's pages, or at GitHub for the rest of the repository."""
    directory = posixpath.dirname(page)

    def replace(found: re.Match[str]) -> str:
        target = found.group("target")
        if "://" in target or target.startswith(("#", "mailto:")):
            return found.group(0)
        path, _, fragment = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(directory, path))
        anchor = f"#{fragment}" if fragment else ""
        for candidate in (_html_path(resolved), posixpath.join(resolved, "index.html")):
            if candidate in site_pages:
                return f"]({posixpath.relpath(candidate, directory or '.')}{anchor}{found.group('title') or ''})"
        url = site.file_url(resolved, directory=(root / resolved).is_dir())
        return f"]({url}{anchor}{found.group('title') or ''})"

    return _LINK.sub(replace, source)


def render_page(source: str, page: str, site: Site, date: str) -> str:
    """The page as a complete HTML document, with the site's navigation and where it was built from."""
    directory = posixpath.dirname(page)
    to_root = "../" * directory.count("/") + ("../" if directory else "")
    navigation = "".join(
        f'<a href="{to_root}{target}">{label}</a>' if target != page else f"<a>{label}</a>"
        for target, label in NAVIGATION
    )
    return TEMPLATE.format(
        title=html.escape(title_of(source)),
        to_root=to_root,
        navigation=navigation,
        ref=html.escape(site.ref),
        commit_url=site.commit_url,
        short=site.revision[:7],
        date=date,
        body=markdown.markdown(source, extensions=list(EXTENSIONS)),
    )


def build(root: Path, output: Path, site: Site) -> list[str]:
    """Write the site to `output`; the paths written, `style.css` included."""
    date = datetime.now(UTC).date().isoformat()
    sources = pages(root)
    written = []
    for page, source in sources.items():
        linked = rewrite_links(source, page, set(sources), site, root)
        target = output / page
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_page(linked, page, site, date), encoding="utf-8")
        written.append(page)
    (output / "style.css").write_text(STYLE, encoding="utf-8")
    return [*written, "style.css"]


def _git(*arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - argv list, no shell
        ["git", "-C", str(ROOT), *arguments],  # noqa: S607 - git from PATH, as the suite does
        capture_output=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation site.")
    parser.add_argument("output", type=Path, help="the directory to write the site to")
    parser.add_argument("--repository", default="cpp-best-practices/project_validator", help="the GitHub repository")
    parser.add_argument("--ref", default=None, help="the branch the pages reflect (default: the current one)")
    parser.add_argument("--revision", default=None, help="the commit the pages reflect (default: HEAD)")
    arguments = parser.parse_args(argv[1:])
    site = Site(
        repository=arguments.repository,
        ref=arguments.ref or _git("branch", "--show-current") or "HEAD",
        revision=arguments.revision or _git("rev-parse", "HEAD"),
    )
    for page in build(ROOT, arguments.output, site):
        print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
