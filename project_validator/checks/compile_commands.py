"""compile_commands.json is exported, so clang-based tooling (clang-tidy, clangd, IDEs) can read the build:
CMAKE_EXPORT_COMPILE_COMMANDS in the CMake files, a preset or on the command line; Meson always writes it."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import compile_commands_answers

compile_commands = answered_check(
    name=PracticeName.COMPILE_COMMANDS,
    description="compile_commands.json is exported (CMAKE_EXPORT_COMPILE_COMMANDS; Meson always writes it)",
    languages=handled(PracticeName.COMPILE_COMMANDS),
    answers=compile_commands_answers,
    judge=judge_any_one,
)
