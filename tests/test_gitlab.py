import unittest

from project_validator.ci.gitlab import expand_parallel, parse_pipeline


class ExpandParallelTests(unittest.TestCase):
    def test_without_matrix_runs_once(self) -> None:
        self.assertEqual(expand_parallel(None), [{}])
        self.assertEqual(expand_parallel(3), [{}])

    def test_each_entry_expands_independently(self) -> None:
        parallel = {"matrix": [{"CC": ["gcc", "clang"], "BUILD": "Debug"}, {"CC": "icx"}]}
        self.assertEqual(
            expand_parallel(parallel),
            [{"CC": "gcc", "BUILD": "Debug"}, {"CC": "clang", "BUILD": "Debug"}, {"CC": "icx"}],
        )


class ParsePipelineTests(unittest.TestCase):
    def test_parses_jobs_and_skips_hidden_trigger_and_reserved_keys(self) -> None:
        pipeline = {
            "stages": ["test"],
            "image": "gcc:14",
            ".template": {"script": ["clang"]},
            "downstream": {"trigger": "other/project"},
            "linux": {"script": ["ctest"]},
            "windows": {"tags": ["saas-windows-medium-amd64"], "script": ["cmake -G 'Visual Studio 17 2022'"]},
        }
        linux, windows = parse_pipeline(pipeline)
        self.assertEqual((linux.os, linux.compilers), ("linux", frozenset({"gcc"})))
        self.assertEqual((windows.os, windows.compilers), ("windows", frozenset({"msvc"})))

    def test_matrix_variables_are_substituted(self) -> None:
        pipeline = {
            "build": {
                "image": "$IMAGE",
                "parallel": {"matrix": [{"IMAGE": ["gcc:14", "silkeh/clang:18"]}]},
                "script": ["make"],
            }
        }
        jobs = parse_pipeline(pipeline)
        self.assertEqual([job.compilers for job in jobs], [frozenset({"gcc"}), frozenset({"clang"})])

    def test_untagged_jobs_without_compilers_use_the_linux_default(self) -> None:
        [job] = parse_pipeline({"test": {"script": ["make test"]}})
        self.assertEqual((job.os, job.compilers, job.default_compiler), ("linux", frozenset({"gcc"}), True))
