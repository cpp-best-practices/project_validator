"""pytest's settings for the unittest suite (`python -m unittest` never reads this file).

Under `-x`, which mutmut always passes, a unittest test stops at its first failing subtest, as unittest's own failfast
mode does: pytest otherwise runs every remaining subtest, so a mutant that the first layout of a whole-matrix test
kills would still pay for every other layout (#307).

Under mutmut, every call of a mutated function passes through its trampoline, which multiplies the frames a call
takes: the readers that recurse to their nesting limits (the shell reader needs some 640 frames at its limits, of the
1,000 Python allows) would overflow on mutmut's frames alone, not the project's. The limit is raised there only, so
that an ordinary run still tests that no nesting exhausts the stack.
"""

from __future__ import annotations

import sys

import pytest
from _pytest.unittest import TestCaseFunction


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    # pytest passes the item to unittest as its result, and unittest's subTest stops on `result.failfast`.
    if isinstance(item, TestCaseFunction) and item.config.getoption("maxfail") == 1:
        item.failfast = True


# Room for mutmut's trampoline frames: a few per call, on the deepest chain an ordinary run takes.
_MUTATED_RECURSION_LIMIT = 5000


def pytest_collection_finish(session: pytest.Session) -> None:
    # Collection imported the project; a mutated module imports mutmut's trampoline.
    if "mutmut.mutation.trampoline" in sys.modules:
        sys.setrecursionlimit(max(sys.getrecursionlimit(), _MUTATED_RECURSION_LIMIT))
