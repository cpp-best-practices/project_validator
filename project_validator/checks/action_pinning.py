"""The reusable CI steps a project runs are pinned to commits, so a moved tag or a pushed branch cannot change them."""

import re
from collections.abc import Iterator

from project_validator import yaml_support
from project_validator.core import Context, Result, check

FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
SHORT_COMMIT = re.compile(r"[0-9a-f]{7,39}")
VERSION_TAG = re.compile(r"v?\d+(?:\.\d+)*(?:[-+][\w.]+)?")
# Actions GitHub itself publishes, which --allow-official-tags lets be pinned to tags.
OFFICIAL_OWNERS = ("actions/", "github/")
HINT = (
    "pin each action to the full commit of its release, e.g. actions/checkout@<40-character SHA> # v4.2.2; "
    "Dependabot and Renovate keep such pins up to date"
)

UNPINNED = "not pinned"
BRANCH = "pinned to a branch"
TAG = "pinned to a tag"
SHORT = "pinned to an abbreviated commit"


def pinning(reference: str, *, allow_official_tags: bool = False) -> str | None:
    """How loosely `reference` is pinned; None when it is pinned to a commit or is local to the repository."""
    if reference.startswith("./"):
        return None
    if reference.startswith("docker://"):
        return None if "@sha256:" in reference else TAG
    name, _, ref = reference.partition("@")
    if not ref:
        return UNPINNED
    if FULL_COMMIT.fullmatch(ref):
        return None
    if SHORT_COMMIT.fullmatch(ref):
        return SHORT
    if VERSION_TAG.fullmatch(ref):
        return None if allow_official_tags and name.startswith(OFFICIAL_OWNERS) else TAG
    return BRANCH


def _references(context: Context) -> Iterator[tuple[str, str]]:
    """(CI file, reference) for every reusable step of every CI file whose provider has them."""
    for ci_file in context.ci_files:
        if (references := ci_file.provider.step_references) is not None:
            try:
                document = yaml_support.load(context.project.read_text(ci_file.path))
            except yaml_support.YamlError:
                continue
            yield from ((ci_file.path, reference) for reference in dict.fromkeys(references(document)))


@check(name="action-pinning", description="The actions CI uses are pinned to full commit SHAs")
def action_pinning(context: Context) -> Result:
    if not any(ci_file.provider.step_references for ci_file in context.ci_files):
        return Result.skipped("no CI configuration with reusable steps")
    allow = context.options.allow_official_tags
    found = [
        (path, reference, pinning(reference, allow_official_tags=allow)) for path, reference in _references(context)
    ]
    loose = [f"{path}: {reference} ({how})" for path, reference, how in found if how]
    count = sum(1 for _, reference, _ in found if not reference.startswith("./"))
    if any(how in {UNPINNED, BRANCH} for *_, how in found):
        return Result.failed(f"{len(loose)} of {count} actions are not pinned to a commit", *loose, HINT)
    if loose:
        return Result.warned(f"{len(loose)} of {count} actions are pinned to a tag rather than a commit", *loose, HINT)
    if not count:
        return Result.passed("CI uses no actions from other repositories")
    return Result.passed(
        "1 action is pinned to a commit" if count == 1 else f"all {count} actions are pinned to a commit"
    )
