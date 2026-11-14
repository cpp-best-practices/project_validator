"""Sanitizers are used: AddressSanitizer and UndefinedBehaviorSanitizer in some configuration of a C/C++ build (one of
the two warns, neither fails), Miri or `-Zsanitizer` for Rust, the race detector (`go test -race`) for Go. Which
sanitizers, where `ci-build-types` asks that each platform builds with and without any."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_settings
from project_validator.questions.practices import sanitizer_answers

sanitizers = answered_check(
    name=PracticeName.SANITIZERS,
    description="Sanitizers are used in some configuration: AddressSanitizer and UndefinedBehaviorSanitizer for "
    "C/C++ (one of the two warns), cargo miri test or -Zsanitizer for Rust, go test -race for Go",
    languages=handled(PracticeName.SANITIZERS),
    answers=sanitizer_answers,
    judge=judge_settings,
)
