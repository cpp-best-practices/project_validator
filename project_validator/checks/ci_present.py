from __future__ import annotations

from project_validator.ci.local_checks import entry_command
from project_validator.core import Context, Result, check


@check(name="ci-present", description="The project has continuous integration configured", ci_only=True)
def ci_present(context: Context) -> Result:
    if context.local_pipeline:
        commands = ", ".join(entry_command(ci_file.path) for ci_file in context.ci_files)
        return Result.warned(
            f"no CI configuration; the local checks ({commands}) are read as the pipeline, so the project is judged "
            "at an entry level",
            "run the same checks in CI (GitHub Actions, GitLab CI, ...) on every change",
        )
    if not context.ci_files:
        # A provider with no configuration file (OCaml-CI) is not looked for.
        searched = ", ".join(provider.name for provider in context.providers if provider.files or provider.directories)
        return Result.failed(f"no CI configuration found (looked for {searched})")
    live = context.live_ci_files
    if not live:  # a CI that no longer runs is no CI; ci-current says why each is defunct
        defunct = "; ".join(f"{found.provider} ({', '.join(found.paths)})" for found in context.ci_currency.defunct)
        return Result.failed(f"only defunct CI configuration found: {defunct}; see ci-current")
    providers = dict.fromkeys(ci_file.provider.name for ci_file in live)
    return Result.passed(f"CI configuration found for {', '.join(providers)}", *(ci_file.path for ci_file in live))
