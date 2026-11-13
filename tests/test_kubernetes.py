"""The Kubernetes profile: a format recognised by content, whose files are YAML; its tests, lints and policy
scanners."""

from __future__ import annotations

import unittest

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.kubernetes import KUBERNETES_ECOSYSTEM
from project_validator.facts.roles import role
from project_validator.facts.structure import Unit
from tests.layouts.kubernetes import MANIFEST
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Kubernetes manifests"
CHART = {"charts/shop/Chart.yaml": "apiVersion: v2\nname: shop\nversion: 0.1.0\n"}
UNITTEST = {"charts/shop/tests/deployment_test.yaml": "suite: deployment\ntests:\n  - it: runs\n    asserts: []\n"}
HOOK = {
    "charts/shop/templates/tests/test-connection.yaml": (
        'apiVersion: v1\nkind: Pod\nmetadata:\n  name: test\n  annotations:\n    "helm.sh/hook": test\n'
    )
}
TEMPLATE = {
    "charts/shop/templates/deployment.yaml": (
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {{ .Chart.Name }}\n"
    )
}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_charts_kustomizations_and_manifests_in_their_directories_are_the_format(self) -> None:
        recognised = (
            CHART,
            {"deploy/kustomization.yaml": "resources:\n  - deployment.yaml\n"},
            {"k8s/deployment.yaml": MANIFEST},
            {"infra/Manifests/app.yml": MANIFEST},
        )
        for files in recognised:
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(
                    (structure.languages, structure.formats), (frozenset(), frozenset({"Kubernetes", "YAML"}))
                )
                self.assertEqual(structure.recognised_by["Kubernetes"], ("content",))
        # A file with the keys outside a manifests directory may be another tool's; a workflow has no such keys.
        for files in ({"catalog-info.yaml": MANIFEST}, {".github/workflows/ci.yml": "on: push\njobs: {}\n"}):
            with self.subTest(files=files), temp_project(files) as root:
                self.assertEqual(make_context(root).structure.formats, frozenset({"YAML"}))

    def test_the_format_is_in_the_root_unit_and_named_templates_are_accounted_for(self) -> None:
        files = {**CHART, "charts/shop/templates/_helpers.tpl": '{{- define "shop.name" -}}shop{{- end -}}\n'}
        with temp_project(files) as root:
            context = make_context(root)
            self.assertEqual(context.structure.unrecognised_suffixes, ())
            [unit] = context.facts.of(Unit)
        self.assertEqual(
            (unit.directory, unit.languages, unit.formats), (".", frozenset(), frozenset({"Kubernetes", "YAML"}))
        )
        self.assertEqual((KUBERNETES_ECOSYSTEM.kind, KUBERNETES_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in ("helm lint charts/shop", "kubectl apply -f k8s", "ct install", "uses: helm/kind-action@v1"):
            with self.subTest(text=text):
                self.assertTrue(uses(KUBERNETES_ECOSYSTEM, text))
        for text in ("npm test", "docker build ."):
            with self.subTest(text=text):
                self.assertFalse(uses(KUBERNETES_ECOSYSTEM, text))


class TemplateTests(unittest.TestCase):
    def test_a_charts_templates_are_templates_not_judged_as_yaml(self) -> None:
        self.assertEqual(role("charts/shop/templates/deployment.yaml"), "template")
        self.assertEqual(role("charts/shop/templates/tests/test-connection.yaml"), "template")
        self.assertEqual(role("charts/shop/values.yaml"), "product")
        result = run_in_layout(self, LAYOUT, data_wellformed, TEMPLATE)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn(
            "charts/shop/templates/deployment.yaml: not parsed, a template, rendered before it is read", result.details
        )


class KubernetesTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_helm_unittest_and_the_test_hooks_are_the_tests(self) -> None:
        cases = (
            ({**UNITTEST, **_ci("helm unittest charts/shop")}, Status.PASS),
            ({**HOOK, **_ci("ct install --charts charts/shop")}, Status.PASS),
            ({**HOOK, **_ci("helm test shop")}, Status.PASS),
            ({**HOOK, **_ci("ct lint-and-install")}, Status.PASS),
            ({**UNITTEST, **_ci("helm lint charts/shop")}, Status.WARN),
            (_ci("helm unittest charts/shop"), Status.FAIL),
        )
        for files, status in cases:
            with self.subTest(files=files):
                self.assertEqual(self._run(tests_run, files).status, status)

    def test_the_lints_analyse_and_the_policy_scanners_analyse_and_scan(self) -> None:
        for line, tool in (("helm lint charts/shop", "helm lint"), ("ct lint --all", "chart-testing")):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)), Result.passed(f"{tool} runs"))
                self.assertIn(self._run(security_scanning, _ci(line)).status, (Status.WARN, Status.FAIL))
        for files, tool in (
            (_ci("kube-linter lint k8s"), "kube-linter"),
            (github_action("stackrox/kube-linter-action@v1", directory="k8s"), "kube-linter"),
            (_ci("polaris audit --audit-path k8s"), "polaris"),
            (_ci("kyverno apply policies --resource k8s/deployment.yaml"), "kyverno"),
            (_ci("kube-score score k8s/*.yaml"), "kube-score"),
            (_ci("checkov -d k8s"), "checkov"),
            (_ci("trivy config k8s"), "trivy"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(static_analysis, files), Result.passed(f"{tool} runs"))
                self.assertEqual(
                    self._run(security_scanning, files),
                    Result.passed(f"CI scans the code for security problems with {tool}"),
                )
        configured = {".kube-linter.yaml": "checks:\n  addAllBuiltIn: true\n", **_ci("kube-linter lint k8s")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("kube-linter (.kube-linter.yaml) runs"))
        self.assertEqual(self._run(static_analysis, _ci("kubectl apply -f k8s")).status, Status.FAIL)
