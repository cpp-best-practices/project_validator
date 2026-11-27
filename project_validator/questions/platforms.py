"""The platform questions: for each language, which OSes and toolchains (compilers, or toolchain versions) its CI jobs
run on, and which build configurations each of those builds."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from project_validator.build_configurations import BuildConfiguration
from project_validator.ecosystems import registered
from project_validator.facts import CiConfiguration, Facts, Unknown
from project_validator.facts.axes import ToolchainAxis, axis_of
from project_validator.facts.jobs import Job
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, language_wide

type Platform = tuple[str, str]
_JOBS = "the jobs and commands"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformAnswer:
    """The language's CI jobs (each described), the platforms (OS, toolchain) they run on with the build
    configurations each builds, the OSes of the jobs that name no toolchain, how many jobs name one on a runner of
    unknown OS, and what of CI was read only heuristically."""

    language: str
    unit: str
    axis: ToolchainAxis
    answer: Answer
    jobs: tuple[str, ...]
    platforms: tuple[tuple[Platform, frozenset[BuildConfiguration]], ...]
    notes: tuple[str, ...]
    unversioned: tuple[str, ...] = ()
    unplaced: int = 0

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


def _placed(
    jobs: tuple[Job, ...], axis: ToolchainAxis, facts: Facts
) -> tuple[dict[Platform, set[BuildConfiguration]], set[str], int]:
    """The configurations each platform builds, the OSes of the jobs that name no toolchain, and how many jobs run on
    a runner of unknown OS (ghostty's namespace-profile runners, with a toolchain or without)."""
    found: defaultdict[Platform, set[BuildConfiguration]] = defaultdict(set)
    unversioned: set[str] = set()
    unplaced = 0
    for job in jobs:
        toolchains = axis.toolchains(job, facts)
        if job.os == "unknown":
            unplaced += 1
            continue
        if not toolchains:
            unversioned.add(job.os)
        for toolchain in toolchains:
            found[(job.os, toolchain)] |= job.configurations
    return found, unversioned, unplaced


def _of_language(job: Job, language: str, axis: ToolchainAxis, facts: Facts) -> bool:
    """Whether a job is one of the language's: it builds with or runs an ecosystem of the language, or sets up one of
    its toolchains. A housekeeping job (a labeler, an artifact cleanup) is no platform of any language (upstream
    #227)."""
    labels = {ecosystem.label for ecosystem in registered() if language in ecosystem.languages}
    return bool(job.ecosystems & labels) or bool(axis.toolchains(job, facts))


def platform_answer(language: str, facts: Facts) -> PlatformAnswer | None:
    """Where CI runs `language`, in the language's own jobs; None when no axis covers it. No CI at all is the answer
    NO."""
    axis = axis_of(language, facts)
    if axis is None:
        return None
    jobs = tuple(job for job in facts.of(Job) if _of_language(job, language, axis, facts))
    found, unversioned, unplaced = _placed(jobs, axis, facts)
    notes = tuple(
        dict.fromkeys(f"{fact.origin.path}: {fact.reason}" for fact in facts.of(Unknown) if fact.subject == _JOBS)
    )
    return PlatformAnswer(
        language=language,
        unit=".",
        axis=axis,
        answer=Answer.YES if facts.of(CiConfiguration) else Answer.NO,
        jobs=tuple(_described(job, axis, facts) for job in jobs),
        platforms=tuple((platform, frozenset(configurations)) for platform, configurations in sorted(found.items())),
        notes=notes,
        unversioned=tuple(sorted(unversioned)),
        unplaced=unplaced,
    )


def _described(job: Job, axis: ToolchainAxis, facts: Facts) -> str:
    toolchains = ", ".join(sorted(axis.toolchains(job, facts))) or f"no {axis.noun}"
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
