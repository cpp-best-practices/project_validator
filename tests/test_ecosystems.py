import unittest
from typing import ClassVar

from project_validator.core import Check, Context, Result, Status
from project_validator.ecosystems import (
    BUILT_IN,
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    applies_to,
    check_each_ecosystem,
    combined,
    ecosystems_for,
    isolated_registry,
    register,
    registered,
)
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import make_context, temp_project


class EcosystemsForTests(unittest.TestCase):
    def test_the_supported_ecosystems_of_the_languages(self) -> None:
        self.assertEqual(ecosystems_for(frozenset({"C++", "Python"}), BUILT_IN), (C_AND_CXX, PYTHON))
        self.assertEqual(ecosystems_for(frozenset({"Rust", "Python"}), (C_AND_CXX, RUST)), (RUST,))

    def test_no_ecosystem_for_unknown_languages(self) -> None:
        self.assertEqual(ecosystems_for(frozenset(), BUILT_IN), ())

    def test_no_ecosystem_when_none_of_the_supported_ones_is_used(self) -> None:
        self.assertEqual(ecosystems_for(C_FAMILY, (PYTHON, RUST)), ())


class CheckEachEcosystemTests(unittest.TestCase):
    RESULTS: ClassVar[dict[Ecosystem, Result]] = {
        C_AND_CXX: Result.warned("c warned", "c detail"),
        PYTHON: Result.passed("python passed", "python detail"),
        RUST: Result.failed("rust failed"),
    }

    def _judge(self, files: dict[str, str]) -> Result:
        with temp_project(files) as root:
            return check_each_ecosystem(make_context(root), self.RESULTS, lambda result, _: result)

    def test_a_single_ecosystem_result_is_unchanged(self) -> None:
        self.assertEqual(self._judge({"Cargo.toml": ""}), self.RESULTS[RUST])
        self.assertEqual(self._judge({"main.c": ""}), self.RESULTS[C_AND_CXX])

    def test_a_project_of_no_recognised_ecosystem_is_skipped(self) -> None:
        self.assertEqual(
            self._judge({"README.md": ""}), Result(status=Status.SKIP, message="no recognised ecosystem in the project")
        )

    def test_several_ecosystems_combine_into_the_worst_result_with_labelled_findings(self) -> None:
        self.assertEqual(
            self._judge({"main.cpp": "", "setup.py": ""}),
            Result.warned("C/C++: c warned; Python: python passed", "C/C++: c detail", "Python: python detail"),
        )
        self.assertEqual(self._judge({"main.c": "", "Cargo.toml": "", "setup.py": ""}).status, Status.FAIL)


ALPHA = BuildSystem(name="Alpha", files=("alpha.txt",))
BETA = BuildSystem(name="Beta", files=("beta.txt",))
WITH_DEFAULT = Ecosystem(label="X", languages=frozenset({"X"}), build_systems=(ALPHA, BETA), default_build_system=ALPHA)
WITHOUT_DEFAULT = Ecosystem(label="Y", languages=frozenset({"Y"}), build_systems=(ALPHA, BETA))


class BuildSystemTests(unittest.TestCase):
    def test_a_project_without_the_ecosystems_build_systems_uses_the_default(self) -> None:
        self.assertEqual(WITH_DEFAULT.used_build_systems(frozenset({"Cargo"})), (ALPHA,))
        self.assertEqual(WITH_DEFAULT.used_build_systems(frozenset({"Beta"})), (BETA,))
        self.assertEqual(WITHOUT_DEFAULT.used_build_systems(frozenset()), ())
        self.assertEqual(repr(WITH_DEFAULT), "Ecosystem(X)")


class CombinedTests(unittest.TestCase):
    SKIPPED = Result(status=Status.SKIP, message="not applicable")

    def test_skipped_ecosystems_are_left_out(self) -> None:
        self.assertEqual(combined({C_AND_CXX: self.SKIPPED, PYTHON: Result.failed("no")}), Result.failed("no"))

    def test_a_skip_only_when_every_ecosystem_is_skipped(self) -> None:
        result = combined({C_AND_CXX: self.SKIPPED, PYTHON: self.SKIPPED})
        self.assertEqual(result.status, Status.SKIP)
        # The same result for every ecosystem is said once.
        self.assertEqual(result.message, "not applicable")


class RegistryTests(unittest.TestCase):
    def test_registering_the_same_ecosystem_again_does_nothing(self) -> None:
        with isolated_registry():
            register(WITH_DEFAULT)
            register(WITH_DEFAULT)
            self.assertEqual(registered(), (*BUILT_IN, WITH_DEFAULT))

    def test_a_check_limited_by_languages_applies_to_the_ecosystems_of_those_languages(self) -> None:
        def run(_: Context) -> Result:
            return Result.passed("")

        self.assertEqual(applies_to(Check(name="c", description="", run=run, languages=frozenset({"C"}))), ("C/C++",))
        self.assertEqual(applies_to(Check(name="any", description="", run=run)), ())
