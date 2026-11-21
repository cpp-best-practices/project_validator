"""pytest's settings for the unittest suite (`python -m unittest` never reads this file).

Under `-x`, which mutmut always passes, a unittest test stops at its first failing subtest, as unittest's own failfast
mode does: pytest otherwise runs every remaining subtest, so a mutant that the first layout of a whole-matrix test
kills would still pay for every other layout (#307).
"""

from __future__ import annotations

import pytest
from _pytest.unittest import TestCaseFunction


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    # pytest passes the item to unittest as its result, and unittest's subTest stops on `result.failfast`.
    if isinstance(item, TestCaseFunction) and item.config.getoption("maxfail") == 1:
        item.failfast = True
