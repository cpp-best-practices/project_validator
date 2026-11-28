"""The plain text report, for CI logs and terminals without rich: what was detected, then one greppable line per check
(`[STATUS] check: message`, each detail indented below it, said once), then the totals and, with `--score`, the score.
"""

from __future__ import annotations

from project_validator.analysis import Analysis
from project_validator.runner import Report
from project_validator.score import Score, floor_percent
from project_validator.views.common import (
    ABOUT_NOTE,
    ABOUT_TITLE,
    about_rows,
    ci_summary,
    dedupe,
    ecosystems,
    files_by_language,
    host_summary,
    partly_read,
    reading,
    role_judgement,
    role_line,
    score_parts,
    summary,
    units,
    unrecognised,
)
from project_validator.words import folder

NEXT_STEPS = 5  # how many next steps the report lists


def detected_lines(analysis: Analysis) -> list[str]:
    """What was detected, and how it was read."""
    if analysis.structure is None:
        return [f"Detected: nothing, the project could not be read: {analysis.error}"]
    lines = ["Detected:"]
    lines += [f"  {label}: {signals}" for label, signals in ecosystems(analysis)] or ["  no recognised language"]
    lines += [f"  Where: {name}: {count} in {where}" for name, count, where in files_by_language(analysis)]
    for directory, role, systems, names in units(analysis):
        lines.append(f"  Unit {folder(directory, slash=False)} ({role}): built with {systems}; {names}")
    lines += [f"  Code of {role_line(summary_)}: {role_judgement(summary_)}" for summary_ in analysis.roles]
    if found := unrecognised(analysis):
        lines.append(f"  Not recognised: {found}")
    lines.append(f"  CI: {ci_summary(analysis)}")
    lines.append(f"  Host: {host_summary(analysis)}")
    lines.append(f"  Read: {reading(analysis)}")
    lines += [f"  Read in part: {found}" for found in partly_read(analysis)]
    return lines


def about_lines(analysis: Analysis) -> list[str]:
    """What is shown of the project without being judged; nothing when there is none."""
    rows = about_rows(analysis)
    return [f"{ABOUT_TITLE} ({ABOUT_NOTE}):", *(f"  {label}: {text}" for label, text in rows)] if rows else []


def report_lines(reports: list[Report]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        lines.append(f"[{report.result.status}] {report.check.name}: {report.result.message}")
        lines.extend(f"    {detail}" for detail in dedupe(report.result.details))
    return lines


def score_lines(scored: Score, *, markdown: bool = False, steps: int = NEXT_STEPS) -> list[str]:
    title = "Score:"
    lines = [f"**{title}** {scored.summary()}" if markdown else f"{title} {scored.summary()}"]
    for heading, rows in score_parts(scored)[1:]:
        lines.append(f"By {heading}:")
        lines.extend(
            f"  - {name}: {floor_percent(percent)}% ({filled:g} of {slots:g} slots)"
            for name, percent, filled, slots in rows
        )
    if scored.next_steps:
        lines.append("Next steps:")
        lines.extend(f"  - {step.describe()}" for step in scored.next_steps[:steps])
    return lines


def render(analysis: Analysis, *, scored: bool = False) -> str:
    """The report: what was detected, each check, the totals, and the score when `scored`."""
    about = about_lines(analysis)
    lines = [*detected_lines(analysis), *([""] if about else []), *about]
    lines += ["", *report_lines(list(analysis.reports)), "", summary(analysis.reports)]
    if scored and analysis.score is not None:
        lines += ["", *score_lines(analysis.score)]
    return "\n".join(lines)


__all__ = ["NEXT_STEPS", "about_lines", "detected_lines", "render", "report_lines", "score_lines"]
