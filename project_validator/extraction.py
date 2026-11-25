"""How the fact database is built: the extractors, in the order each one's facts are needed by the next.

1. The project's structure: its source files and languages (or formats), build files and units (`facts.structure`).
2. Its data files, each parsed by its format's parser (`facts.wellformed`), and its schemas, each read for what it
   declares (`facts.declaration`).
3. What the repository holds: the files git does not track, and the build outputs it does, of the project's
   languages only (`facts.repository`).
4. Its test files, as each language defines them (`facts.testing`); with `--build`, what the probes find by
   building it.
5. CI: its files, jobs, and the commands and reusable steps each job runs, each command followed by what it runs
   in turn (`ci`, `facts.expansion`).
6. What each job builds with and on, from what it runs (`ci.job_facts`).
7. The settings the configuration files hold, those the commands name included (`facts.settings`).
8. The tools the commands run, and what each run provides (`facts.tools`).

A plugin adds components to a stage (an expander, a settings reader, a tool); it never changes the order. The
components of each stage are asked of its module (`tools.known_tools()`), so that a test may stand others in.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sized
from typing import TYPE_CHECKING

from project_validator import ci
from project_validator.core import ExtractionError, Progress
from project_validator.facts import (
    Facts,
    declaration,
    expansion,
    outputs,
    repository,
    settings,
    structure,
    testing,
    tools,
    wellformed,
)

if TYPE_CHECKING:
    from project_validator.core import Context, Project


def _stage[T](context: Context, name: str, compute: Callable[[], T], before: Facts | None = None) -> T:
    """What a stage computes, its start and end told to the context's observers (with how long it took and how many
    facts it found, beyond those it was given, `before`); an extractor that raises makes the whole extraction an
    `ExtractionError` naming it."""
    context.notify(Progress(kind="stage", name=name, done=False))
    started = time.perf_counter()
    try:
        found = compute()
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(name, error) from error
    count = len(found.all) if isinstance(found, Facts) else len(found) if isinstance(found, Sized) else 0
    count -= len(before.all) if before is not None else 0
    seconds = time.perf_counter() - started
    context.notify(Progress(kind="stage", name=name, done=True, seconds=seconds, found=count))
    return found


def _data_facts(project: Project, found: Facts) -> Facts:
    """The data files, parsed, and the schemas, read for what they declare."""
    found = found + wellformed.data_file_facts(project, found, wellformed.known_parsers())
    return found + declaration.declaration_facts(project, found, declaration.known_declarers())


def _project_facts(context: Context) -> Facts:
    """The stages that read the project's own files: its structure, data, repository, tests (and build probes)."""
    project = context.project
    found = _stage(context, "the project's structure", lambda: Facts(structure.structure_facts(project)))
    found = _stage(context, "the data files", lambda: _data_facts(project, found), before=found)
    # Only the build outputs of the project's languages, and of its formats (a documentation site's), can be
    # committed by it.
    names = structure.project_languages(found) | structure.project_formats(found)
    built = (out for out in outputs.known_build_outputs() if out.languages & names)
    found = _stage(context, "the repository", lambda: found + repository.repository_facts(project, built), before=found)
    found = _stage(
        context,
        "the test files",
        lambda: found + testing.test_file_facts(project, found, testing.known_test_files()),
        before=found,
    )
    if context.options.build:
        probed = (fact for probe in testing.known_probes() for fact in probe.run(project, context.options))
        found = _stage(context, "the build probes", lambda: found + probed, before=found)
    return found


def extract_facts(context: Context) -> Facts:
    """Every fact about the project `context` reads, in the stages above; an `ExtractionError` when a stage fails."""
    project = context.project
    found = _project_facts(context)
    jobs = _stage(context, "the CI configuration", lambda: ci.ci_facts(project, context.live_ci_files))
    expanders, actions = expansion.known_expanders(), expansion.known_actions()
    found = _stage(
        context, "the CI commands", lambda: found + expansion.expanded(jobs, context, expanders, actions), before=found
    )
    found = _stage(context, "the CI jobs", lambda: found + ci.job_facts(found, project), before=found)
    found = _stage(context, "the units CI tests", lambda: structure.ci_test_units(project, found), before=found)
    found = _stage(
        context,
        "the settings",
        lambda: found + settings.settings_facts(context, settings.known_settings_readers(), found),
        before=found,
    )
    # Only the tools of the project's languages and formats can run on it: a run of another language's tool answers
    # nothing a question asks, and would only grow the facts with every profile that shares the tool.
    names = structure.project_languages(found) | structure.project_formats(found)
    used = tuple(tool for tool in tools.known_tools() if tool.languages & names)
    return _stage(context, "the tool runs", lambda: found + tools.tool_runs(found, used), before=found)


__all__ = ["extract_facts"]
