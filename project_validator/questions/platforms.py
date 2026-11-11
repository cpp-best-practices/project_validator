"""The platform questions: for each language, which OSes and toolchains (compilers, or toolchain versions) its CI jobs
run on, and which build configurations each of those builds."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from project_validator.build_configurations import BuildConfiguration
from project_validator.facts import CiConfiguration, Facts, Unknown
from project_validator.facts.axes import ToolchainAxis, axis_of
from project_validator.facts.jobs import Job
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, language_wide

type Platform = tuple[str, str]
_JOBS = "the jobs and commands"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformAnswer:
    """The language's CI jobs (each described), the platforms (OS, toolchain) they run on with the build
    configurations each builds, and what of CI was read only heuristically."""

    language: str
    unit: str
    axis: ToolchainAxis
    answer: Answer
    jobs: tuple[str, ...]
    platforms: tuple[tuple[Platform, frozenset[BuildConfiguration]], ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            axis=self.axis.noun,
            platforms=[
                {"os": os, self.axis.noun: toolchain, "configurations": sorted(map(str, configurations))}
                for (os, toolchain), configurations in self.platforms
            ],
            notes=list(self.notes),
        )


def platform_answer(language: str, facts: Facts) -> PlatformAnswer | None:
    """Where CI runs `language`; None when no axis covers it. No CI at all is the answer NO."""
    axis = axis_of(language)
    if axis is None:
        return None
    jobs = facts.of(Job)
    found: defaultdict[Platform, set[BuildConfiguration]] = defaultdict(set)
    for job in jobs:
        for toolchain in axis.of_job(job) if job.os != "unknown" else ():
            found[(job.os, toolchain)] |= job.configurations
    notes = tuple(
        dict.fromkeys(f"{fact.origin.path}: {fact.reason}" for fact in facts.of(Unknown) if fact.subject == _JOBS)
    )
    return PlatformAnswer(
        language=language,
        unit=".",
        axis=axis,
        answer=Answer.YES if facts.of(CiConfiguration) else Answer.NO,
        jobs=tuple(_described(job, axis) for job in jobs),
        platforms=tuple((platform, frozenset(configurations)) for platform, configurations in sorted(found.items())),
        notes=notes,
    )


def _described(job: Job, axis: ToolchainAxis) -> str:
    toolchains = ", ".join(sorted(axis.of_job(job))) or f"no {axis.noun}"
    suffix = " (runner default)" if axis.runner_default(job) else ""
    return f"{job.name}: {job.os} / {toolchains}{suffix}"


def platform_answers(language: str, facts: Facts) -> LanguageAnswers[PlatformAnswer]:
    return language_wide(language, facts, lambda: platform_answer(language, facts))


PLATFORMS_QUESTION = Question(
    name="platforms",
    description="On which OSes and toolchains does CI run each language, building which configurations?",
    answer=platform_answers,
)

__all__ = ["PLATFORMS_QUESTION", "Platform", "PlatformAnswer", "platform_answer", "platform_answers"]
