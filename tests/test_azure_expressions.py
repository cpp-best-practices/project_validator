"""Azure Pipelines template expressions, evaluated where a template is expanded: parameters take their values, and
`${{ if }}`/`${{ elseif }}`/`${{ else }}` and `${{ each }}` expand the mapping or sequence they are keys of."""

from __future__ import annotations

import unittest

from project_validator.ci.azure_expressions import Unevaluated, expand


class ValueTests(unittest.TestCase):
    def test_a_parameter_takes_its_value_and_a_whole_expression_keeps_its_type(self) -> None:
        scope = {"parameters": {"name": "unit", "targets": ["a", "b"]}}
        self.assertEqual(expand("ansible-test ${{ parameters.name }} -v", scope), "ansible-test unit -v")
        self.assertEqual(expand("${{ parameters.targets }}", scope), ["a", "b"])
        self.assertEqual(expand({"${{ parameters.name }}": 1}, scope), {"unit": 1})

    def test_a_variable_is_left_for_the_jobs_variables(self) -> None:
        for scope in ({}, {"variables": {"other": "x"}}):
            self.assertEqual(expand("echo ${{ variables.os }}", scope), "echo ${{ variables.os }}")
        self.assertEqual(expand("${{ variables.os }}", {"variables": {"os": "linux"}}), "linux")

    def test_functions(self) -> None:
        scope = {"parameters": {"groups": [], "name": "", "test": "sanity", "n": 3}}
        for expression, expected in (
            ("format('{0}/{{1}}', 'x')", "x/{1}"),
            ("coalesce(parameters.name, parameters.test)", "sanity"),
            ("eq(length(parameters.groups), 0)", True),
            ("not(eq('A', 'a'))", False),
            ("and(true, ne(parameters.test, 'unit'))", True),
            ("or(false, in(parameters.test, 'unit', 'Sanity'))", True),
            ("notIn(parameters.test, 'unit')", True),
            ("gt(parameters.n, 2)", True),
            ("le(parameters.n, 2)", False),
            ("contains('Hello', 'ELL')", True),
            ("startsWith(parameters.test, 'SAN')", True),
            ("endsWith(parameters.test, 'x')", False),
            ("upper(replace(parameters.test, 's', 'z'))", "ZANITY"),
            ("join('-', parameters.groups)", ""),
            ("parameters.n >= 3 && parameters.test == 'SANITY'", True),
            ("!(parameters.n < 3) || false", True),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(expand("${{ " + expression + " }}", scope), expected)

    def test_what_is_not_known_before_the_pipeline_runs_is_unevaluated(self) -> None:
        for text in ("${{ dependencies.a }}", "${{ counter('x', 1) }}", "${{ eq( }}", "${{ insert }}"):
            with self.subTest(text=text), self.assertRaises(Unevaluated):
                expand({"a": [text]} if "insert" not in text else {text: {}}, {"parameters": {}})


class DirectiveTests(unittest.TestCase):
    def test_if_elseif_and_else_insert_the_branch_that_holds(self) -> None:
        steps = [
            {"${{ if eq(parameters.os, 'linux') }}": [{"script": "make"}]},
            {"${{ elseif eq(parameters.os, 'mac') }}": [{"script": "xcodebuild"}]},
            {"${{ else }}": [{"script": "msbuild"}]},
            {"script": "ctest"},
        ]
        for os, first in (("linux", "make"), ("Mac", "xcodebuild"), ("windows", "msbuild")):
            with self.subTest(os=os):
                expanded = expand(steps, {"parameters": {"os": os}})
                self.assertEqual(expanded, [{"script": first}, {"script": "ctest"}])
        mapping = {"a": 1, "${{ if parameters.on }}": {"b": 2}, "${{ else }}": {"c": 3}}
        self.assertEqual(expand(mapping, {"parameters": {"on": True}}), {"a": 1, "b": 2})
        self.assertEqual(expand(mapping, {"parameters": {"on": False}}), {"a": 1, "c": 3})

    def test_a_condition_that_cannot_be_decided_inserts_each_branch_it_could_take(self) -> None:
        """command-line-api's `${{ if in(variables['Build.Reason'], 'PullRequest') }}`: a variable the pipeline
        sets as it runs. Each branch is possible, as the Make reader follows a recipe the environment decides."""
        steps = [
            {"${{ if in(variables['Build.Reason'], 'PullRequest') }}": [{"script": "a"}]},
            {"${{ elseif eq(parameters.os, 'linux') }}": [{"script": "b"}]},
            {"${{ elseif eq(parameters.os, 'mac') }}": [{"script": "c"}]},
            {"${{ else }}": [{"script": "d"}]},
        ]
        expanded = expand(steps, {"parameters": {"os": "linux"}, "variables": {}})
        # b holds, so c and d cannot run whether or not a does.
        self.assertEqual(expanded, [{"script": "a"}, {"script": "b"}])
        expanded = expand(steps, {"parameters": {"os": "windows"}, "variables": {}})
        self.assertEqual(expanded, [{"script": "a"}, {"script": "d"}])
        # A value that cannot be decided is still unevaluated.
        with self.assertRaises(Unevaluated):
            expand("${{ variables['Build.Reason'] }}", {"variables": {}})
        # A variable of the pipeline's own that is not set where the template is expanded (a matrix leg's) is empty
        # there, as Azure evaluates it: command-line-api's `coalesce(variables._BuildConfig, 'Release')`.
        self.assertEqual(expand("${{ coalesce(variables._BuildConfig, 'Release') }}", {"variables": {}}), "Release")

    def test_an_else_without_an_if_is_unevaluated(self) -> None:
        """Its if must come just before it: a step between ends the chain."""
        for steps in (
            [{"script": "x"}, {"${{ else }}": [{"script": "y"}]}],
            [{"${{ if false }}": [{"script": "x"}]}, {"script": "y", "env": {}}, {"${{ else }}": [{"script": "z"}]}],
            [
                {"${{ if true }}": [{"script": "x"}]},
                {"${{ else }}": [{"script": "y"}]},
                {"${{ else }}": [{"script": "z"}]},
            ],
        ):
            with self.subTest(steps=steps), self.assertRaises(Unevaluated):
                expand(steps, {})

    def test_each_inserts_its_body_for_each_item(self) -> None:
        """ansible's matrix.yml: `${{ each target in parameters.targets }}` makes a job of each target."""
        jobs = [{"${{ each t in parameters.targets }}": [{"name": "${{ coalesce(t.name, t.test) }}"}]}]
        targets = [{"test": "sanity"}, {"name": "Units", "test": "units"}]
        self.assertEqual(expand(jobs, {"parameters": {"targets": targets}}), [{"name": "sanity"}, {"name": "Units"}])
        over_mapping = {"${{ each pair in parameters.env }}": {"${{ pair.key }}": "${{ pair.value }}"}}
        self.assertEqual(expand(over_mapping, {"parameters": {"env": {"A": "1", "B": "2"}}}), {"A": "1", "B": "2"})
