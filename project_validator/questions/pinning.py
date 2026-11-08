"""The pinning question: which reusable steps does the CI configuration refer to, and what is each pinned to?

Answered for the project as a whole: a reference is a property of the file, whether or not the step runs. Local
steps (`./.github/actions/x`) are the project's own and are not references. The answer is yes when every reference is
pinned to a full commit; what the policy allows besides (tags of GitHub's own actions) is the policy's.
"""

import re
from dataclasses import dataclass

from project_validator.ci import CiProvider
from project_validator.components import known
from project_validator.facts import CiConfiguration, Facts, StepReference
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict

FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
SHORT_COMMIT = re.compile(r"[0-9a-f]{7,39}")
VERSION_TAG = re.compile(r"v?\d+(?:\.\d+)*(?:[-+][\w.]+)?")
# Actions GitHub itself publishes.
OFFICIAL_OWNERS = ("actions/", "github/")

UNPINNED = "not pinned"
BRANCH = "pinned to a branch"
TAG = "pinned to a tag"
SHORT = "pinned to an abbreviated commit"


def pinning(reference: str) -> str | None:
    """How loosely `reference` is pinned; None when it is pinned to a commit (or a digest) or is local."""
    if reference.startswith("./"):
        return None
    if reference.startswith("docker://"):
        return None if "@sha256:" in reference else TAG
    _, _, ref = reference.partition("@")
    if not ref:
        return UNPINNED
    if FULL_COMMIT.fullmatch(ref):
        return None
    if SHORT_COMMIT.fullmatch(ref):
        return SHORT
    return TAG if VERSION_TAG.fullmatch(ref) else BRANCH


@dataclass(frozen=True, slots=True, kw_only=True)
class Reference:
    """A reference in the CI file `path`, `how` loosely it is pinned (None: to a commit), and whether it is to an
    action GitHub itself publishes."""

    path: str
    reference: str
    how: str | None
    official: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PinningAnswer:
    """Impossible when no CI provider the project uses has reusable steps; yes when every reference is pinned to a
    commit."""

    language: str = ""
    unit: str = "."
    answer: Answer
    references: tuple[Reference, ...] = ()

    def loose(self) -> tuple[Reference, ...]:
        return tuple(reference for reference in self.references if reference.how)

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            references=[
                {"path": found.path, "reference": found.reference, "pinning": found.how} for found in self.references
            ],
        )


def _has_reusable_steps(facts: Facts) -> bool:
    providers = {provider.name: provider for provider in known(CiProvider)}
    used = (providers.get(configuration.provider) for configuration in facts.of(CiConfiguration))
    return any(provider is not None and provider.step_references is not None for provider in used)


def pinning_answer(facts: Facts, language: str = "") -> PinningAnswer:
    """What the CI configuration's reusable steps are pinned to, by the facts."""
    if not _has_reusable_steps(facts):
        return PinningAnswer(language=language, answer=Answer.IMPOSSIBLE)
    references = tuple(
        Reference(
            path=fact.origin.path,
            reference=fact.reference,
            how=pinning(fact.reference),
            official=fact.reference.startswith(OFFICIAL_OWNERS),
        )
        for fact in facts.of(StepReference)
        if not fact.reference.startswith("./")
    )
    loose = any(reference.how for reference in references)
    return PinningAnswer(language=language, answer=Answer.NO if loose else Answer.YES, references=references)


def pinned_steps(language: str, facts: Facts) -> LanguageAnswers[PinningAnswer]:
    return LanguageAnswers(language=language, units=(pinning_answer(facts, language),))


PINNING_QUESTION = Question(
    name="action-pinning",
    description="Which reusable steps does CI refer to, and what is each pinned to?",
    answer=pinned_steps,
)

__all__ = [
    "BRANCH",
    "PINNING_QUESTION",
    "SHORT",
    "TAG",
    "UNPINNED",
    "PinningAnswer",
    "Reference",
    "pinned_steps",
    "pinning",
    "pinning_answer",
]
