"""Binary hardening is on: what the build inserts into the binary to make it harder to exploit (stack protectors,
control-flow protection, checked library calls, position-independent executables, release overflow checks), for each
compiler CI builds with where a language has several.

It is not code security scanning (see `project_validator.facts.security`) nor dependency auditing (see
`project_validator.facts.audit`); a language that builds no binary asks for none.
"""

from project_validator.facts.practices import HARDENING, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_hardening
from project_validator.questions.practices import hardening_answers

hardening = answered_check(
    name=HARDENING,
    description="Security hardening options are enabled",
    languages=handled(HARDENING),
    answers=hardening_answers,
    judge=judge_hardening,
)
