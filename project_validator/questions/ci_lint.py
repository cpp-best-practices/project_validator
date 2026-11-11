"""The CI lint question: for each CI provider the project uses, does CI (or a pre-commit hook) run a linter of that
provider's configuration? Answered for the project as a whole. The linters are searched for in the configuration
text itself, so a provider read only heuristically hides nothing here."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator.ci import CiProvider
from project_validator.components import known
from project_validator.facts import CiConfiguration, Facts
from project_validator.facts.practices import named
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderLinting:
    """A CI provider the project uses: the `linters` of its configuration that run, whether any is known for it
    (`lintable`), and `hint`, how to add one."""

    provider: str
    linters: tuple[str, ...]
    lintable: bool
    hint: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CiLintAnswer:
    """Impossible when no CI provider used has a known linter; yes when each that has one is linted."""

    language: str = ""
    unit: str = "."
    answer: Answer
    providers: tuple[ProviderLinting, ...] = ()

    def lintable(self) -> tuple[ProviderLinting, ...]:
        return tuple(found for found in self.providers if found.lintable)

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            providers={
                found.provider: {"linters": list(found.linters), "lintable": found.lintable} for found in self.providers
            },
        )


def ci_lint_answer(facts: Facts, language: str = "") -> CiLintAnswer:
    """Which CI configuration is linted, by the facts and what the known providers say lints theirs."""
    providers = {provider.name: provider for provider in known(CiProvider)}
    used = dict.fromkeys(configuration.provider for configuration in facts.of(CiConfiguration))
    found = tuple(
        ProviderLinting(
            provider=name,
            linters=tuple(named(facts, provider.linters)) if provider is not None else (),
            lintable=provider is not None and bool(provider.linters),
            hint=provider.lint_hint if provider is not None else "",
        )
        for name in used
        for provider in (providers.get(name),)
    )
    lintable = [provider for provider in found if provider.lintable]
    if not lintable:
        answer = Answer.IMPOSSIBLE
    else:
        answer = Answer.YES if all(provider.linters for provider in lintable) else Answer.NO
    return CiLintAnswer(language=language, answer=answer, providers=found)


def ci_linting(language: str, facts: Facts) -> LanguageAnswers[CiLintAnswer]:
    return LanguageAnswers(language=language, units=(ci_lint_answer(facts, language),))


CI_LINT_QUESTION = Question(
    name="ci-lint", description="Does CI lint its own configuration, for each provider it uses?", answer=ci_linting
)

__all__ = ["CI_LINT_QUESTION", "CiLintAnswer", "ProviderLinting", "ci_lint_answer", "ci_linting"]
