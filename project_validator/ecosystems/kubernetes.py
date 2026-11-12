"""Kubernetes: Helm charts (`Chart.yaml`), kustomizations (`kustomization.yaml`) and manifests (YAML with `apiVersion`,
`kind` and `metadata`, under a manifests directory), a format recognised by content: its files are YAML, the Data
format's, and a chart's templates are templates, rendered before they are read. What is asked of it is hygiene: `helm
lint`, chart-testing and kube-linter lint it (`static-analysis`); the policy scanners (kube-linter, checkov, `trivy
config`, KICS, polaris, kyverno, kube-score) scan it (`security-scanning`); and its tests run (`tests-run`):
helm-unittest's, or the chart's test hooks `helm test` (and `ct install`) runs.

kubeconform, kubeval and `helm lint --strict` validate the manifests, and a chart's values, against their schemas
(`schema-validation`). Left for the checks they belong to: Kubernetes versions as a platform axis (a format has no
toolchain), and `Chart.lock` as a dependency rule (#24).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.schema import validated, validator
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import all_of, combined, defined_by, starts, when, with_option
from project_validator.tools.misconfiguration import misconfiguration_scanner, misconfiguration_scanners

KUBERNETES = "Kubernetes"
KUBERNETES_ONLY = frozenset({KUBERNETES})
# What the manifests, and the tests, are written in.
YAML = frozenset({"YAML"})


# --- Recognition ----------------------------------------------------------------------------------------------------

_CHART_FILES = frozenset({"Chart.yaml", "Chart.yml"})
_KUSTOMIZATION_FILES = frozenset({"kustomization.yaml", "kustomization.yml", "Kustomization"})
# A manifest is YAML with these keys at the top level, in a directory that holds manifests; a file with the keys
# elsewhere may be another tool's (a Backstage catalog, a kind cluster configuration).
_MANIFEST_DIRECTORIES = frozenset(
    {
        "k8s",
        "kubernetes",
        "kube",
        "manifests",
        "manifest",
        "deploy",
        "deployment",
        "deployments",
        "kustomize",
        "overlays",
        "base",
        "charts",
        "chart",
        "helm",
        "templates",
    }
)
_MANIFEST_KEYS = tuple(re.compile(rf"^{key}:", re.MULTILINE) for key in ("apiVersion", "kind", "metadata"))


def _is_manifest(project: Project, path: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(path).parts[:-1]]
    if not any(part in _MANIFEST_DIRECTORIES for part in parts):
        return False
    head = project.read_head(path)
    return all(key.search(head) for key in _MANIFEST_KEYS)


def kubernetes_project(project: Project) -> frozenset[str]:
    """Whether the project describes Kubernetes resources: a Helm chart, a kustomization, or manifests in a directory
    of them."""
    for path in project.files():
        name = PurePosixPath(path).name
        if name in _CHART_FILES or name in _KUSTOMIZATION_FILES:
            return KUBERNETES_ONLY
        if name.endswith((".yaml", ".yml")) and _is_manifest(project, path):
            return KUBERNETES_ONLY
    return frozenset()


KUBERNETES_ECOSYSTEM = Ecosystem(
    label="Kubernetes",
    kind="format",
    languages=KUBERNETES_ONLY,
    # A chart's named templates (`_helpers.tpl`) belong to it without being a format of their own.
    ambiguous_suffixes={".tpl": None},
    detect=kubernetes_project,
    ci_programs=(
        ("helm",),
        ("kubectl",),
        ("kustomize",),
        ("ct",),
        ("kube-linter",),
        ("kubeconform",),
        ("kubeval",),
        ("kind",),
        ("k3d",),
        ("minikube",),
        ("polaris",),
        ("kyverno",),
        ("kube-score",),
    ),
    ci_usage=re.compile(
        r"(?<![\w-])(?:kind-action|k3d-action|chart-testing-action|setup-helm|setup-kubectl|k8s-deploy"
        r"|kube-linter-action)\b"
    ),
)


# --- Tests ----------------------------------------------------------------------------------------------------------

HELM_UNITTEST_TESTS = TestFiles(
    name="helm-unittest tests (tests/*_test.yaml)",
    languages=KUBERNETES_ONLY,
    path=re.compile(r"(?:^|/)tests/.+_test\.ya?ml$"),
    contains=re.compile(r"^suite:", re.MULTILINE),
    written_in=YAML,
)
HELM_TEST_HOOKS = TestFiles(
    name="Helm test hooks (templates/tests/*.yaml)",
    languages=KUBERNETES_ONLY,
    path=re.compile(r"(?:^|/)templates/tests/.+\.ya?ml$"),
    contains=re.compile(r"helm\.sh/hook['\"]?:\s*['\"]?test"),
    written_in=YAML,
)
HELM_UNITTEST = test_runner(
    name="helm-unittest",
    languages=KUBERNETES_ONLY,
    how="helm unittest <chart>",
    runs=when(starts(("helm", "unittest")), tested),
    tests=tests_of(HELM_UNITTEST_TESTS.name),
)
# chart-testing's `ct install` installs each changed chart and runs its tests.
HELM_TEST = test_runner(
    name="helm test",
    languages=KUBERNETES_ONLY,
    how="helm test <release> (or ct install, which installs the chart and runs its test hooks)",
    runs=when(starts(("helm", "test"), ("ct", "install"), ("ct", "lint-and-install")), tested),
    tests=tests_of(HELM_TEST_HOOKS.name),
)


# --- Schema validation ----------------------------------------------------------------------------------------------

KUBECONFORM = validator(
    name="kubeconform",
    languages=KUBERNETES_ONLY,
    how="kubeconform -strict <manifests> (helm template <chart> | kubeconform -strict)",
    validates=when(starts(("kubeconform",)), validated),
)
KUBEVAL = validator(
    name="kubeval",
    languages=KUBERNETES_ONLY,
    how="kubeval <manifests>",
    validates=when(starts(("kubeval",)), validated),
)
# `helm lint --strict` validates the chart's values against its values.schema.json, failing on a warning.
HELM_LINT_STRICT = validator(
    name="helm lint --strict",
    languages=KUBERNETES_ONLY,
    how="helm lint --strict <chart>",
    validates=when(all_of(starts(("helm", "lint")), with_option("--strict")), validated),
)


# --- Lints and policy scanners --------------------------------------------------------------------------------------

HELM_LINT = analyzer(
    name="helm lint",
    languages=KUBERNETES_ONLY,
    how="helm lint <chart>",
    analyses=when(starts(("helm", "lint")), analysed),
)
CHART_TESTING = analyzer(
    name="chart-testing",
    languages=KUBERNETES_ONLY,
    how="ct lint",
    analyses=when(starts(("ct", "lint"), ("ct", "lint-and-install")), analysed),
)
KUBE_LINTER_SETTINGS = file_reader("kube-linter", (".kube-linter.yaml", ".kube-linter.yml"))
_KUBE_LINTER_RUNS = starts(("kube-linter", "lint"))
# kube-linter's checks are security and reliability policies: a non-root user, resource limits, no privileged pods.
KUBE_LINTER = combined(
    analyzer(
        name="kube-linter",
        languages=KUBERNETES_ONLY,
        how="kube-linter lint <manifests> (or stackrox/kube-linter-action)",
        analyses=when(_KUBE_LINTER_RUNS, analysed),
        rules=defined_by(files=(KUBE_LINTER_SETTINGS.name,)),
    ),
    scanner(
        name="kube-linter",
        languages=KUBERNETES_ONLY,
        how="kube-linter lint <manifests>",
        scans=when(_KUBE_LINTER_RUNS, scanned),
    ),
)
POLARIS = misconfiguration_scanner(
    "polaris", KUBERNETES_ONLY, "polaris audit --audit-path <manifests>", starts(("polaris", "audit"))
)
KYVERNO = misconfiguration_scanner(
    "kyverno",
    KUBERNETES_ONLY,
    "kyverno apply <policies> --resource <manifests>",
    starts(("kyverno", "apply"), ("kyverno", "test")),
)
KUBE_SCORE = misconfiguration_scanner(
    "kube-score", KUBERNETES_ONLY, "kube-score score <manifests>", starts(("kube-score", "score"))
)
MISCONFIGURATION_SCANNERS = misconfiguration_scanners(KUBERNETES_ONLY)


def _kube_linter_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    configuration = ("--config", inputs["config"]) if inputs.get("config") else ()
    return (("kube-linter", "lint", *configuration, inputs.get("directory", ".")),)


KUBE_LINTER_ACTION = Action(name="stackrox/kube-linter-action", runs=_kube_linter_action)
