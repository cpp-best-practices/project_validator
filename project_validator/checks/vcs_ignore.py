"""A version control ignore file keeps the build outputs out of version control."""

from dataclasses import replace

from project_validator.checks.committed_artifacts import output_languages
from project_validator.core import Check, Context, Result
from project_validator.judging import answered_check
from project_validator.policy.outputs import judge_ignored
from project_validator.questions.outputs import ignore_files, ignored_outputs
from project_validator.tools.version_control import IGNORE_FILES

IGNORE_FILE_NAMES = ", ".join(IGNORE_FILES)


def _needing_an_ignore_file(ignored: Check) -> Check:
    """`ignored`, failing first when the project has no ignore file at all."""

    def run(context: Context) -> Result:
        if not ignore_files(context.facts):
            return Result.failed(
                f"no version control ignore file found ({IGNORE_FILE_NAMES}); build outputs can be committed by "
                "accident",
                "consider adding a .gitignore (or your version control system's equivalent) that ignores build outputs",
            )
        return ignored.run(context)

    return replace(ignored, run=run)


vcs_ignore = _needing_an_ignore_file(
    answered_check(
        name="vcs-ignore",
        description="A .gitignore (or .hgignore, .bzrignore, ...) keeps build outputs (e.g. build/, __pycache__/, "
        "target/) out of version control",
        languages=output_languages,
        answers=ignored_outputs,
        judge=judge_ignored,
    )
)
