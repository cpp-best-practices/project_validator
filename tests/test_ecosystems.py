import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, ECOSYSTEMS, PYTHON, RUST, check_each_ecosystem, ecosystems_for
from project_validator.structure import C_FAMILY
from tests.support import make_context, temp_project


class EcosystemsForTests(unittest.TestCase):
    def test_the_supported_ecosystems_of_the_languages(self) -> None:
        self.assertEqual(ecosystems_for(frozenset({"C++", "Python"}), ECOSYSTEMS), (C_AND_CXX, PYTHON))
        self.assertEqual(ecosystems_for(frozenset({"Rust", "Python"}), (C_AND_CXX, RUST)), (RUST,))

    def test_unknown_languages_are_judged_as_c_and_cxx(self) -> None:
        self.assertEqual(ecosystems_for(frozenset(), ECOSYSTEMS), (C_AND_CXX,))

    def test_every_supported_ecosystem_when_none_is_used(self) -> None:
        self.assertEqual(ecosystems_for(frozenset(), (PYTHON, RUST)), (PYTHON, RUST))
        self.assertEqual(ecosystems_for(C_FAMILY, (PYTHON,)), (PYTHON,))


class CheckEachEcosystemTests(unittest.TestCase):
    RESULTS = {
        C_AND_CXX: Result.warned("c warned", "c detail"),
        PYTHON: Result.passed("python passed", "python detail"),
        RUST: Result.failed("rust failed"),
    }

    def _judge(self, files: dict[str, str]) -> Result:
        with temp_project(files) as root:
            return check_each_ecosystem(make_context(root), self.RESULTS, lambda result, _: result)

    def test_a_single_ecosystem_result_is_unchanged(self) -> None:
        self.assertEqual(self._judge({"Cargo.toml": ""}), self.RESULTS[RUST])
        self.assertEqual(self._judge({"README.md": ""}), self.RESULTS[C_AND_CXX])

    def test_several_ecosystems_combine_into_the_worst_result_with_labelled_findings(self) -> None:
        self.assertEqual(
            self._judge({"main.cpp": "", "setup.py": ""}),
            Result.warned("C/C++: c warned; Python: python passed", "C/C++: c detail", "Python: python detail"),
        )
        self.assertEqual(self._judge({"main.c": "", "Cargo.toml": "", "setup.py": ""}).status, Status.FAIL)
