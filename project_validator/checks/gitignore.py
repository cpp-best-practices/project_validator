import re
from dataclasses import dataclass

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of

GITIGNORE = ".gitignore"


def _ignored_at_top_level(names: str) -> re.Pattern[str]:
    """Entries that ignore one of `names` at the top of the repository, as a directory or with all of its contents."""
    return re.compile(rf"(?:\*\*/|/)?(?:{names})(?:/\**)?", re.IGNORECASE)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildOutputs:
    """The build outputs of an ecosystem that must never be committed, and the .gitignore entries that ignore them."""

    name: str
    entries: re.Pattern[str]
    hint: str


BUILD_OUTPUTS = {
    C_AND_CXX: BuildOutputs(
        name="the build directory",
        entries=_ignored_at_top_level(r"(?:\[Bb\]uild|_?build|out|cmake-build)(?:[-_*][\w*-]*)?"),
        hint="consider ignoring the build directory (e.g. build/ and out/)",
    ),
    PYTHON: BuildOutputs(
        name="Python bytecode",
        entries=_ignored_at_top_level(r"__pycache__|\*\.py(?:c|\[[cod]+\])"),
        hint="consider ignoring __pycache__/ and *.py[cod]",
    ),
    RUST: BuildOutputs(
        name="the target directory",
        entries=_ignored_at_top_level("target"),
        hint="consider ignoring /target",
    ),
}


def _ignore_entries(text: str) -> tuple[str, ...]:
    """The entries of a .gitignore; blank lines, comments and negations ignore nothing."""
    lines = (line.strip() for line in text.splitlines())
    return tuple(line for line in lines if line and not line.startswith(("#", "!")))


def _outputs_ignored(outputs: BuildOutputs, context: Context) -> Result:
    entries = _ignore_entries(context.project.read_text(GITIGNORE))
    if entry := next((entry for entry in entries if outputs.entries.fullmatch(entry)), None):
        return Result.passed(f"{GITIGNORE} ignores {entry}")
    return Result.warned(f"{GITIGNORE} does not ignore {outputs.name}", outputs.hint)


@check(
    name="gitignore",
    description="A .gitignore keeps build outputs (e.g. build/, __pycache__/, target/) out of version control",
    languages=languages_of(BUILD_OUTPUTS),
)
def gitignore(context: Context) -> Result:
    if not context.project.exists(GITIGNORE):
        return Result.failed(
            f"no {GITIGNORE} found; build outputs can be committed by accident",
            f"consider adding a {GITIGNORE} that ignores build outputs",
        )
    return check_each_ecosystem(context, BUILD_OUTPUTS, _outputs_ignored)
