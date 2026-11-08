"""The build output policies: every version control system the project is set up for ignores the build outputs, and
none is committed."""

from project_validator.core import Result
from project_validator.questions import Answer
from project_validator.questions.outputs import CommittedAnswer, IgnoreAnswer

# How many of the committed outputs are listed.
LISTED = 5
COMMITTED_HINT = "remove them from version control (git rm -r --cached <path>) and ignore them"


def _skipped(language: str) -> Result:
    return Result.skipped(f"no known build output of {language}")


def judge_ignored(answer: IgnoreAnswer, *, allow_unknown: bool = False) -> Result:
    """Passes when every ignore file ignores every build output; warns, with how, for each one some file does not."""
    if answer.answer is Answer.IMPOSSIBLE:
        return _skipped(answer.language)
    missing = [output for output in answer.outputs if output.unignored()]
    if missing:
        messages = (
            f"{', '.join(files)} {'does' if len(files) == 1 else 'do'} not ignore {output.name}"
            for output in missing
            if (files := output.unignored())
        )
        return Result.warned("; ".join(messages), *dict.fromkeys(output.hint for output in missing))
    found = (f"{path} ignores {entry}" for output in answer.outputs for path, entry in output.entries)
    return Result.passed("; ".join(dict.fromkeys(found)))


def judge_committed(answer: CommittedAnswer, *, allow_unknown: bool = False) -> Result:
    """Fails when a build output is committed, listing the first few."""
    if answer.answer is Answer.IMPOSSIBLE:
        return _skipped(answer.language)
    if not (count := len(answer.committed)):
        return Result.passed("no build outputs are committed")
    return Result.failed(
        f"{count} build output{'s are' if count != 1 else ' is'} committed",
        *answer.committed[:LISTED],
        *((f"and {count - LISTED} more",) if count > LISTED else ()),
        COMMITTED_HINT,
    )


__all__ = ["COMMITTED_HINT", "judge_committed", "judge_ignored"]
