# Terraform

Recognised by `.tf`, `.tofu` and `.tfvars` files; `.hcl` files (the tests, `*.tftest.hcl`, and the lockfile,
`.terraform.lock.hcl`) are Terraform's once the project is known to be. OpenTofu reads the same configuration with the
same commands, so `tofu` counts wherever `terraform` does. A configuration has no build system: it is a directory of
`.tf` files, and the project is one unit (a `modules/` child is judged with the root that uses it).

The checks of a compiled language (coverage, compiler warnings, hardening, build types) do not apply: there is no code
to compile or to cover.

## `code-formatting`

`terraform fmt -check` (`-recursive` for the modules), or `tofu fmt -check`, which fails on a file it would change;
the pre-commit-terraform hook `terraform_fmt` rewrites them. `fmt` has one style, so running it is enough.

## `static-analysis`

`terraform validate` (after `terraform init -backend=false`, which downloads the providers it needs; the `init` is not
checked for), tflint (`.tflint.hcl` enables the provider rulesets), or one of the misconfiguration scanners below,
whose rules are what static analysis means for infrastructure code. The pre-commit-terraform hooks
`terraform_validate` and `terraform_tflint` count.

## `security-scanning`

A misconfiguration scanner: checkov (`checkov -d .`, `bridgecrewio/checkov-action`), trivy (`trivy config .`, or
`trivy fs` with `misconfig` among its `--scanners`; `aquasecurity/trivy-action` with `scan-type: config`), KICS
(`kics scan`, `checkmarx/kics-github-action`), terrascan (`terrascan scan`, `tenable/terrascan-action`) or tfsec
(`tfsec`, `aquasecurity/tfsec-action`; it is now part of trivy). The pre-commit-terraform hooks `terraform_checkov`,
`terraform_trivy` and `terraform_tfsec` count. CodeQL and GitLab SAST do not scan HCL.

## `tests-run`

`terraform test` or `tofu test`, with test files to run: `*.tftest.hcl` or `*.tofutest.hcl`. Terratest tests are
Go tests, judged by the Go profile.

## `dependency-management`

The providers `required_providers` names (or `provider` blocks imply) are dependencies, and `terraform init` locks
their versions and hashes in `.terraform.lock.hcl`, which must be committed. A configuration that names no provider has
no dependencies to lock.

## `dependency-updates`

Dependabot's `terraform` package ecosystem and Renovate's terraform manager update the providers and modules.

## `committed-artifacts`

A committed `.terraform/` directory, state (`*.tfstate`, `*.tfstate.*`), plan (`*.tfplan`) or crash log fails: the
state holds secrets and belongs in a remote backend.

## `vcs-ignore`

The ignore rules keep out `.terraform/`, and the state, plans and crash logs (`*.tfstate`, `*.tfstate.*`, `*.tfplan`,
`crash.log`).

## `platform-matrix`

The toolchains are Terraform or OpenTofu versions: `terraform_version` given to `hashicorp/setup-terraform`,
`tofu_version` given to `opentofu/setup-opentofu`, or the tag of a `hashicorp/terraform` or `ghcr.io/opentofu/opentofu`
image. A job that runs `terraform` (or tflint, checkov, tfsec, terrascan, KICS, `trivy config`) without naming a
version uses the runner's. A matrix of cloud providers or environments is not a platform.
