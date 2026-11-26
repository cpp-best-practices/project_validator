"""Code security scanners of many languages at once: CodeQL, GitLab SAST, semgrep and DevSkim. Each knows the languages
it reads (`CODEQL_LANGUAGES`, `GITLAB_SAST_LANGUAGES`, `SEMGREP_LANGUAGES`, `DEVSKIM_LANGUAGES`); a profile asks for
the scanners of its languages (`multi_language_scanners`) and gets those that read one of them, for those languages
only."""

from __future__ import annotations

import re
from collections.abc import Callable

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.shell import split_words
from project_validator.facts.tools import Run, Tool, starts, when

# A GitLab template include is the jobs of the template, run as a marker command (see `project_validator.ci.gitlab`).
GITLAB_TEMPLATE = "gitlab-template"


_SAST_TEMPLATE = re.compile(r"(?:^|/)SAST(?:\.latest)?\.gitlab-ci\.yml")


def _gitlab_sast(command: Command, _facts: Facts) -> Run | None:
    """GitLab's SAST template (`Security/SAST.gitlab-ci.yml`, `Jobs/SAST.latest.gitlab-ci.yml`)."""
    argv = resolved(command)
    return scanned() if argv[:1] == (GITLAB_TEMPLATE,) and any(map(_SAST_TEMPLATE.search, argv)) else None


# The languages each scanner reads. CodeQL's are its supported languages; GitLab SAST's are semgrep's in its analyzer
# plus sobelow's Elixir; semgrep's are the languages of its rules among those with a profile here.
CODEQL_LANGUAGES = frozenset(
    {"C", "C++", "C#", "Go", "Java", "Kotlin", "JavaScript", "TypeScript", "Python", "Ruby", "Rust", "Swift"}
)
GITLAB_SAST_LANGUAGES = CODEQL_LANGUAGES | {"PHP", "Scala", "Elixir", "Objective-C"}
SEMGREP_LANGUAGES = GITLAB_SAST_LANGUAGES | {"Lua", "Julia", "OCaml", "Clojure", "Dart"}
# DevSkim's rules: the languages of its rule set that have a profile here.
DEVSKIM_LANGUAGES = frozenset(
    {
        "C",
        "C++",
        "C#",
        "Go",
        "Java",
        "JavaScript",
        "TypeScript",
        "Objective-C",
        "PHP",
        "Python",
        "Ruby",
        "Rust",
        "Swift",
    }
)


def _codeql(read: frozenset[str]) -> Tool:
    return scanner(
        name="CodeQL",
        languages=read,
        how="CodeQL (github/codeql-action)",
        scans=when(starts(("codeql", "database", "analyze")), scanned),
    )


def _gitlab(read: frozenset[str]) -> Tool:
    return scanner(
        name="GitLab SAST", languages=read, how="GitLab SAST (Security/SAST.gitlab-ci.yml)", scans=_gitlab_sast
    )


def _semgrep(read: frozenset[str]) -> Tool:
    return scanner(
        name="semgrep",
        languages=read,
        how="semgrep ci",
        scans=when(starts(("semgrep", "ci"), ("semgrep", "scan"), ("semgrep", "--config")), scanned),
    )


def _devskim(read: frozenset[str]) -> Tool:
    """DevSkim (microsoft/DevSkim-Action) uploads its findings as SARIF and never fails CI (Humanizer): an advisory
    scanner (upstream #224), recognised where a project runs it, never suggested."""
    return scanner(
        name="DevSkim",
        languages=read,
        how="",
        scans=when(
            starts(("devskim", "analyze")), lambda: scanned(advisory="it only uploads SARIF: no finding fails CI")
        ),
    )


_SCANNERS: tuple[tuple[frozenset[str], Callable[[frozenset[str]], Tool]], ...] = (
    (CODEQL_LANGUAGES, _codeql),
    (GITLAB_SAST_LANGUAGES, _gitlab),
    (SEMGREP_LANGUAGES, _semgrep),
    (DEVSKIM_LANGUAGES, _devskim),
)


def multi_language_scanners(languages: frozenset[str]) -> tuple[Tool, ...]:
    """CodeQL, GitLab SAST, semgrep and DevSkim, each as a code security scanner of those of `languages` it reads; a
    scanner that reads none of them is left out."""
    return tuple(make(read) for reads, make in _SCANNERS if (read := languages & reads))


DEVSKIM_ACTION = Action(name="microsoft/DevSkim-Action", runs=lambda _inputs: (("devskim", "analyze"),))
CODEQL_ACTION = Action(name="github/codeql-action/analyze", runs=lambda _inputs: (("codeql", "database", "analyze"),))
SEMGREP_ACTIONS = tuple(
    Action(name=name, runs=lambda inputs: (("semgrep", "ci", *split_words(inputs.get("config", ""))),))
    for name in ("returntocorp/semgrep-action", "semgrep/semgrep-action")
)
