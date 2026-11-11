"""How the fact database is built: the extractors, in the order each one's facts are needed by the next.

1. The project's structure: its source files and languages, build files and units (`facts.structure`).
2. What the repository holds: the files git does not track, and the build outputs it does, of the project's
   languages only (`facts.repository`).
3. Its test files, as each language defines them (`facts.testing`); with `--build`, what the probes find by
   building it.
4. CI: its files, jobs, and the commands and reusable steps each job runs, each command followed by what it runs
   in turn (`ci`, `facts.expansion`).
5. What each job builds with and on, from what it runs (`ci.job_facts`).
6. The settings the configuration files hold, those the commands name included (`facts.settings`).
7. The tools the commands run, and what each run provides (`facts.tools`).

A plugin adds components to a stage (an expander, a settings reader, a tool); it never changes the order. The
components of each stage are asked of its module (`tools.known_tools()`), so that a test may stand others in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from project_validator import ci
from project_validator.core import ExtractionError
from project_validator.facts import Facts, expansion, outputs, repository, settings, structure, testing, tools

if TYPE_CHECKING:
    from project_validator.core import Context


def _stage[T](name: str, compute: Callable[[], T]) -> T:
    """What a stage computes; an extractor that raises makes the whole extraction an `ExtractionError` naming it."""
    try:
        return compute()
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(name, error) from error


def extract_facts(context: Context) -> Facts:
    """Every fact about the project `context` reads, in the stages above; an `ExtractionError` when a stage fails."""
    project = context.project
    found = _stage("the project's structure", lambda: Facts(structure.structure_facts(project)))
    # Only the build outputs of the project's languages can be committed by it.
    languages = structure.project_languages(found)
    built = (out for out in outputs.known_build_outputs() if out.languages & languages)
    found = _stage("the repository", lambda: found + repository.repository_facts(project, built))
    found = _stage(
        "the test files", lambda: found + testing.test_file_facts(project, found, testing.known_test_files())
    )
    if context.options.build:
        probed = (fact for probe in testing.known_probes() for fact in probe.run(project, context.options))
        found = _stage("the build probes", lambda: found + probed)
    jobs = _stage("the CI configuration", lambda: ci.ci_facts(project, context.ci_files))
    expanders, actions = expansion.known_expanders(), expansion.known_actions()
    found = _stage("the CI commands", lambda: found + expansion.expanded(jobs, context, expanders, actions))
    found = _stage("the CI jobs", lambda: found + ci.job_facts(found, project))
    found = _stage(
        "the settings", lambda: found + settings.settings_facts(context, settings.known_settings_readers(), found)
    )
    return _stage("the tool runs", lambda: found + tools.tool_runs(found, tools.known_tools()))


__all__ = ["extract_facts"]
