import unittest

from project_validator.ci.github_actions import expand_matrix, parse_workflow, substitute_matrix


class ExpandMatrixTests(unittest.TestCase):
    def test_without_matrix_runs_once(self) -> None:
        self.assertEqual(expand_matrix(None), [{}])

    def test_expression_matrix_cannot_be_expanded(self) -> None:
        self.assertIsNone(expand_matrix("${{ fromJSON(needs.setup.outputs.matrix) }}"))
        self.assertIsNone(expand_matrix({"os": "${{ fromJSON(inputs.os) }}"}))

    def test_cartesian_product(self) -> None:
        self.assertEqual(
            expand_matrix({"os": ["a", "b"], "cc": ["x", "y"]}),
            [{"os": "a", "cc": "x"}, {"os": "a", "cc": "y"}, {"os": "b", "cc": "x"}, {"os": "b", "cc": "y"}],
        )

    def test_exclude_removes_partially_matching_combinations(self) -> None:
        matrix = {"os": ["a", "b"], "cc": ["x", "y"], "exclude": [{"os": "b"}]}
        self.assertEqual(expand_matrix(matrix), [{"os": "a", "cc": "x"}, {"os": "a", "cc": "y"}])

    def test_include_extends_matching_combinations(self) -> None:
        matrix = {"cc": ["gcc", "clang"], "include": [{"cc": "gcc", "cxx": "g++"}, {"extra": "all"}]}
        self.assertEqual(
            expand_matrix(matrix),
            [{"cc": "gcc", "cxx": "g++", "extra": "all"}, {"cc": "clang", "extra": "all"}],
        )

    def test_include_that_would_overwrite_original_values_adds_a_combination(self) -> None:
        matrix = {"cc": ["gcc"], "include": [{"cc": "msvc", "os": "windows"}]}
        self.assertEqual(expand_matrix(matrix), [{"cc": "gcc"}, {"cc": "msvc", "os": "windows"}])

    def test_include_only_matrix(self) -> None:
        self.assertEqual(expand_matrix({"include": [{"os": "a"}, {"os": "b"}]}), [{"os": "a"}, {"os": "b"}])


class SubstituteMatrixTests(unittest.TestCase):
    def test_substitutes_nested_values_and_keeps_unknown_ones(self) -> None:
        combination = {"config": {"os": "windows-latest"}, "cc": "gcc"}
        self.assertEqual(
            substitute_matrix("${{ matrix.config.os }} ${{matrix.cc}} ${{ matrix.nope }}", combination),
            "windows-latest gcc ${{ matrix.nope }}",
        )


class ParseWorkflowTests(unittest.TestCase):
    def test_compilers_come_from_matrix_values(self) -> None:
        workflow = {
            "jobs": {
                "build": {
                    "runs-on": "${{ matrix.config.os }}",
                    "strategy": {"matrix": {"config": [{"os": "ubuntu-latest", "cxx": "clang++"}]}},
                    "steps": [{"run": "install gcc"}],
                }
            }
        }
        [job] = parse_workflow(workflow)
        self.assertEqual((job.os, job.compilers, job.default_compiler), ("linux", frozenset({"clang"}), False))

    def test_compilers_fall_back_to_job_text_then_runner_default(self) -> None:
        workflow = {
            "jobs": {
                "named": {"runs-on": "macos-latest", "steps": [{"run": "brew install gcc"}]},
                "unnamed": {"runs-on": "windows-latest", "steps": [{"run": "cmake --build build"}]},
            }
        }
        named, unnamed = parse_workflow(workflow)
        self.assertEqual(named.compilers, frozenset({"gcc"}))
        self.assertEqual((unnamed.compilers, unnamed.default_compiler), (frozenset({"msvc"}), True))

    def test_container_jobs_run_on_linux(self) -> None:
        workflow = {"jobs": {"c": {"runs-on": "self-hosted", "container": "gcc:14", "steps": []}}}
        self.assertEqual(parse_workflow(workflow)[0].os, "linux")

    def test_reusable_workflow_calls_are_skipped(self) -> None:
        self.assertEqual(parse_workflow({"jobs": {"call": {"uses": "org/repo/.github/workflows/x.yml@v1"}}}), [])

    def test_expression_matrix_is_reported_as_unknown(self) -> None:
        workflow = {"jobs": {"j": {"runs-on": "ubuntu-latest", "strategy": {"matrix": "${{ fromJSON(x) }}"}}}}
        [job] = parse_workflow(workflow)
        self.assertEqual(job.os, "unknown")
        self.assertIn("expression", job.name)

    def test_ignores_documents_without_jobs(self) -> None:
        self.assertEqual(parse_workflow(None), [])
        self.assertEqual(parse_workflow({"name": "x"}), [])
