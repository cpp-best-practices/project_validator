from __future__ import annotations

from project_validator.core import Context, Result, check
from project_validator.facts import ActionStep

DEPENDENCY_UPDATERS = (
    ("Dependabot", (".github/dependabot.yml", ".github/dependabot.yaml")),
    # Every location Renovate documents for a repository's configuration (but package.json's `renovate` key).
    (
        "Renovate",
        (
            "renovate.json",
            "renovate.json5",
            ".github/renovate.json",
            ".github/renovate.json5",
            ".gitlab/renovate.json",
            ".gitlab/renovate.json5",
            ".renovaterc",
            ".renovaterc.json",
            ".renovaterc.json5",
        ),
    ),
    # Scala's update bot: the public instance reads its configuration from one of these; a project running its own
    # instance does so through the action (see `SCALA_STEWARD_ACTION`).
    ("Scala Steward", (".scala-steward.conf", ".github/.scala-steward.conf", ".config/.scala-steward.conf")),
)
SCALA_STEWARD_ACTION = "scala-steward-org/scala-steward-action"


@check(
    name="dependency-updates",
    description="Automated dependency updates are configured (Dependabot, Renovate or Scala Steward)",
)
def dependency_updates(context: Context) -> Result:
    found = {tool: [path for path in paths if context.project.exists(path)] for tool, paths in DEPENDENCY_UPDATERS}
    found["Scala Steward"] += dict.fromkeys(
        step.origin.path for step in context.facts.of(ActionStep) if step.uses.partition("@")[0] == SCALA_STEWARD_ACTION
    )
    if tools := [tool for tool, paths in found.items() if paths]:
        return Result.passed(
            f"automated dependency updates are configured with {', '.join(tools)}",
            *(path for tool in tools for path in found[tool]),
        )
    return Result.warned(
        "no automated dependency updates configured",
        "consider adding .github/dependabot.yml or a Renovate configuration (renovate.json)",
    )
