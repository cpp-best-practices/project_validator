"""The plain text report, for CI logs and terminals without rich: what was detected, then one greppable line per check
(`[STATUS] check: message`, each detail indented below it, said once), then the totals and, with `--score`, the score.
"""

from __future__ import annotations

from project_validator.analysis import Analysis
from project_validator.runner import Report
from project_validator.score import Score
from project_validator.views.common import (
    ci_summary,
    dedupe,
    ecosystems,
    reading,
    role_judgement,
    role_line,
    summary,
    units,
    unrecognised,
)

NEXT_STEPS = 5  # how many next steps the report lists


def detected_lines(analysis: Analysis) -> list[str]:
    """What was detected, and how it was read."""
    if analysis.structure is None:
        return [f"Detected: nothing, the project could not be read: {analysis.error}"]
    lines = ["Detected:"]
    lines += [f"  {label}: {signals}" for label, signals in ecosystems(analysis)] or ["  no recognised language"]
    for directory, role, systems, names in units(analysis):
        where = "the root" if directory == "." else directory
        lines.append(f"  Unit {where} ({role}): built with {systems}; {names}")
    lines += [f"  Code of {role_line(summary_)}: {role_judgement(summary_)}" for summary_ in analysis.roles]
    if found := unrecognised(analysis):
        lines.append(f"  Not recognised: {found}")
    lines.append(f"  CI: {ci_summary(analysis)}")
    lines.append(f"  Read: {reading(analysis)}")
    return lines


def report_lines(reports: list[Report]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        lines.append(f"[{report.result.status}] {report.check.name}: {report.result.message}")
        lines.extend(f"    {detail}" for detail in dedupe(report.result.details))
    return lines


def score_lines(scored: Score, *, markdown: bool = False, steps: int = NEXT_STEPS) -> list[str]:
    title = "Score:"
    lines = [f"**{title}** {scored.summary()}" if markdown else f"{title} {scored.summary()}"]
    if scored.next_steps:
        lines.append("Next steps:")
        lines.extend(f"  - {step.describe()}" for step in scored.next_steps[:steps])
    return lines


def render(analysis: Analysis, *, scored: bool = False) -> str:
    """The report: what was detected, each check, the totals, and the score when `scored`."""
    lines = [*detected_lines(analysis), "", *report_lines(list(analysis.reports)), "", summary(analysis.reports)]
    if scored and analysis.score is not None:
        lines += ["", *score_lines(analysis.score)]
    return "\n".join(lines)


__all__ = ["NEXT_STEPS", "detected_lines", "render", "report_lines", "score_lines"]
