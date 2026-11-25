"""The Starlark of Bazel's BUILD and MODULE.bazel files, read as the rules they call: each top-level call with its
arguments, as literal values where they are written as such."""

from __future__ import annotations

import unittest

from project_validator.build_systems.bazel.syntax import Opaque, Rule, rules

# grpc-proto's BUILD.bazel, shortened.
GRPC_PROTO = """\
# Copyright
load("@rules_proto//proto:defs.bzl", "proto_library")

package(default_visibility = [
    "//visibility:private",
])

proto_library(
    name = "stats_proto",
    srcs = ["grpc/core/stats.proto"],
)

java_proto_library(
    name = "messages_java_proto",
    visibility = ["//visibility:public"],
    deps = [":messages_proto"],
)
"""


class StarlarkTests(unittest.TestCase):
    def test_each_top_level_call_is_a_rule_with_its_arguments(self) -> None:
        found, problems = rules(GRPC_PROTO)
        self.assertEqual(problems, ())
        self.assertEqual(
            [(rule.kind, rule.name, rule.line) for rule in found],
            [
                ("load", None, 2),
                ("package", None, 4),
                ("proto_library", "stats_proto", 8),
                ("java_proto_library", "messages_java_proto", 13),
            ],
        )
        self.assertEqual(found[0].arguments, ("@rules_proto//proto:defs.bzl", "proto_library"))
        self.assertEqual(found[2].attributes, {"name": "stats_proto", "srcs": ["grpc/core/stats.proto"]})

    def test_values(self) -> None:
        text = '''\
COPTS = ["-Wall"]
cc_test(
    name = 'gtest_test',
    size = "small",
    shard_count = 4,
    flaky = True,
    srcs = glob(["test/*.cc"]) + ["main.cc"],
    copts = COPTS + select({"//:windows": ["/W4"], "//conditions:default": ["-Werror"]}),
    env = {"A": "1", 'B': """two
lines""", "C": """\\
$${x[0]}"""},
    tags = [r"raw\\d", "a" "b"],
)
native.cc_library(name = "lib", hdrs = [x + ".h" for x in ["a", "b"]],)
'''
        found, problems = rules(text)
        self.assertEqual(problems, ())
        test, library = found
        self.assertEqual((test.kind, library.kind, library.name), ("cc_test", "native.cc_library", "lib"))
        self.assertEqual(test.attributes["size"], "small")
        self.assertEqual((test.attributes["shard_count"], test.attributes["flaky"]), (4, True))
        self.assertEqual(test.attributes["env"], {"A": "1", "B": "two\nlines", "C": "$${x[0]}"})
        self.assertEqual(test.attributes["tags"], ["raw\\d", "ab"])
        # What is computed, not written as a literal, is opaque: a call, a concatenation, a name, a comprehension.
        for key in ("srcs", "copts"):
            self.assertIsInstance(test.attributes[key], Opaque)
        self.assertIsInstance(library.attributes["hdrs"], Opaque)

    def test_definitions_and_control_flow_are_passed_over(self) -> None:
        """A `.bzl` file's `def` and a BUILD file's `if` or `for` call nothing at the top level."""
        text = "def macro(name):\n    native.cc_test(name = name)\n\n"
        text += 'for n in ["a"]:\n    cc_test(name = n)\n\nsh_test(name = "t")\n'
        self.assertEqual([rule.kind for rule in rules(text)[0]], ["sh_test"])

    def test_a_statement_that_does_not_parse_is_a_problem_and_the_rest_is_read(self) -> None:
        found, problems = rules('cc_test(name = "a",, )\ncc_test(name = "b")\n)\ncc_test(name = "c")\nx = (\n')
        self.assertEqual([rule.name for rule in found], ["b", "c"])
        self.assertEqual([problem.span.line for problem in problems if problem.span], [1, 3, 5])

    def test_rule_is_a_value(self) -> None:
        self.assertEqual(Rule(kind="k", arguments=(), attributes={"name": "n"}, line=1).name, "n")
        self.assertIsNone(Rule(kind="k", arguments=(), attributes={"name": Opaque("x")}, line=1).name)
