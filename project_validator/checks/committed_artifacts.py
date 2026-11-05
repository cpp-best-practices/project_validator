"""No build output is committed: what the ignore rules keep out (see `vcs-ignore`) did not slip in before them."""

from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import BuildOutputs

# How many of the committed outputs are listed.
LISTED = 5
HINT = "remove them from version control (git rm -r --cached <path>) and ignore them"


@practice(
    name="committed-artifacts",
    description="No build outputs (e.g. object files, __pycache__/, target/) are committed",
    rule=BuildOutputs,
)
def committed_artifacts(outputs: BuildOutputs, context: Context) -> Result:
    found = dict.fromkeys(
        artifact for path in context.project.tracked_files() if (artifact := outputs.artifact(path)) is not None
    )
    if not found:
        return Result.passed("no build outputs are committed")
    count = len(found)
    return Result.failed(
        f"{count} build output{'s are' if count != 1 else ' is'} committed",
        *list(found)[:LISTED],
        *((f"and {count - LISTED} more",) if count > LISTED else ()),
        HINT,
    )
