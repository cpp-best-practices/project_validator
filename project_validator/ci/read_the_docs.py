"""Read the Docs: builds a project's documentation site on its own service, on every push, as `.readthedocs.yaml`
describes (upstream #280).

The configuration's one job builds nothing of the project's (it is no platform), and runs what Read the Docs runs:
the configuration's own `build: commands:`, or else `mkdocs build` for an MkDocs site, or `sphinx-build` for a Sphinx
one (the default); `fail_on_warning: true` makes the build fail on a warning (`--strict`, `-W`). Its badge is the
site's build status (devguide); a project set up only in Read the Docs' dashboard has its badge and no file.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load
from project_validator.facts import CiJob, Fact, Origin
from project_validator.facts.expansion import script_facts
from project_validator.facts.shell import command_line
from project_validator.text import pattern

_JOB = "Read the Docs"


def _settings(document: Mapping[str, object], key: str) -> tuple[bool, str | None]:
    """Whether a generator's section fails on a warning, and the configuration file it names."""
    section = document.get(key)
    settings: Mapping[str, object] = section if isinstance(section, Mapping) else {}
    configuration = settings.get("configuration")
    return settings.get("fail_on_warning") is True, configuration if isinstance(configuration, str) else None


def _generator(document: Mapping[str, object]) -> tuple[str, tuple[str, ...]]:
    """The key of the generator the configuration builds with, and the command line Read the Docs runs for it."""
    if isinstance(document.get("mkdocs"), Mapping):
        strict, configuration = _settings(document, "mkdocs")
        named = ("--config-file", configuration) if configuration else ()
        return "mkdocs", ("mkdocs", "build", *named, *(("--strict",) if strict else ()))
    strict, configuration = _settings(document, "sphinx")
    source = (posixpath.dirname(configuration) or ".") if configuration else "docs"
    return "sphinx", ("sphinx-build", "-b", "html", *(("-W",) if strict else ()), source, "_readthedocs/html")


def _facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    if not isinstance(document, Mapping):
        return
    yield CiJob(origin=Origin(path=path), id=_JOB, provider=READ_THE_DOCS.name, name=_JOB, os="linux", builds=False)
    build = document.get("build")
    commands = build.get("commands") if isinstance(build, Mapping) else None
    if isinstance(commands, list):
        for number, line in enumerate(commands):
            if isinstance(line, str):
                yield from script_facts(line, job=_JOB, origin=Origin(path=path, at=("build", "commands", number)))
        return
    key, argv = _generator(document)
    yield from script_facts(command_line(argv), job=_JOB, origin=Origin(path=path, at=(key,)))


READ_THE_DOCS = CiProvider(
    name="Read the Docs",
    files=(".readthedocs.yaml", ".readthedocs.yml", "readthedocs.yaml", "readthedocs.yml"),
    badges=(pattern("Read the Docs", r"readthedocs\.org/projects/\S+/badge|img\.shields\.io/readthedocs/"),),
    configured_elsewhere=True,
    facts=_facts,
)
