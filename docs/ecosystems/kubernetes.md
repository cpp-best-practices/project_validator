# Kubernetes

A format, recognised by content: a Helm chart (`Chart.yaml`), a kustomization (`kustomization.yaml`), or manifests
(YAML with `apiVersion`, `kind` and `metadata` at the top level) in a directory that holds them (`k8s/`,
`manifests/`, `deploy/`, `charts/`, `kustomize/`, …). A file with those keys elsewhere may be another tool's and does
not count. Its files are YAML, the Data format's, so `data-wellformed` judges them as YAML; a chart's `templates/` are
templates, rendered before they are read, so they are noted and not parsed. A chart's named templates (`.tpl`) belong
to it without being a format of their own.

A CI job works with the ecosystem when it runs `helm`, `kubectl`, `kustomize`, `ct`, `kind`, `k3d` or `minikube`, one
of the tools below, or the `helm/kind-action`, `helm/chart-testing-action`, `azure/setup-helm`, `azure/setup-kubectl`
or `azure/k8s-deploy` actions.

## `tests-run`

helm-unittest tests (`tests/*_test.yaml` with a `suite:`) that `helm unittest <chart>` runs, or the chart's test hooks
(`templates/tests/*.yaml` with `helm.sh/hook: test`) that `helm test`, or chart-testing's `ct install`, runs.

## `static-analysis`

`helm lint`, chart-testing (`ct lint`, `ct lint-and-install`), kube-linter (`.kube-linter.yaml`;
`stackrox/kube-linter-action`), and the misconfiguration scanners: checkov, `trivy config`, KICS, polaris
(`polaris audit`), kyverno (`kyverno apply`, `kyverno test`), kube-score.

## `security-scanning`

A policy scanner of the manifests: kube-linter, checkov (`bridgecrewio/checkov-action`), `trivy config`
(`aquasecurity/trivy-action` with `scan-type: config`), KICS (`checkmarx/kics-github-action`), polaris, kyverno,
kube-score.

## `schema-validation`

kubeconform (`kubeconform -strict`, on the manifests or on what `helm template` renders), kubeval, or `helm lint
--strict`, which validates a chart's values against its `values.schema.json`.

## Not judged

`platform-matrix` needs an axis besides the OS, and a format has no toolchain to carry Kubernetes versions on.
`Chart.lock` beside a `Chart.yaml` with dependencies is a dependency rule (#24). The other checks have no tool for
manifests and are skipped.
