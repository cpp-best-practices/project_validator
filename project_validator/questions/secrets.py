"""The secret scanning question: does CI, or a pre-commit hook, run a scanner for committed secrets, and which
scanners are configured? Answered for the project as a whole."""

from dataclasses import dataclass

from project_validator.facts import ConfigurationFile, Facts
from project_validator.facts.practices import named
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict
from project_validator.tools.secret_scanners import CONFIGURED_SCANNERS, SECRET_SCANNERS


@dataclass(frozen=True, slots=True, kw_only=True)
class SecretScanningAnswer:
    """`scanners`: those CI or a hook runs; `configured`: those a configuration file shows are meant to run."""

    language: str = ""
    unit: str = "."
    answer: Answer
    scanners: tuple[str, ...] = ()
    configured: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return answer_dict(self, self.answer, scanners=list(self.scanners), configured=list(self.configured))


def secret_scanning_answer(facts: Facts, language: str = "") -> SecretScanningAnswer:
    scanners = tuple(named(facts, SECRET_SCANNERS))
    read = {fact.reader for fact in facts.of(ConfigurationFile)}
    configured = tuple(name for name in CONFIGURED_SCANNERS if name in read)
    return SecretScanningAnswer(
        language=language,
        answer=Answer.YES if scanners else Answer.NO,
        scanners=scanners,
        configured=configured,
    )


def secrets_scanned(language: str, facts: Facts) -> LanguageAnswers[SecretScanningAnswer]:
    return LanguageAnswers(language=language, units=(secret_scanning_answer(facts, language),))


SECRET_SCANNING_QUESTION = Question(
    name="secret-scanning",
    description="Does CI or a pre-commit hook scan for committed secrets, and which scanners are configured?",
    answer=secrets_scanned,
)

__all__ = ["SECRET_SCANNING_QUESTION", "SecretScanningAnswer", "secret_scanning_answer", "secrets_scanned"]
