"""Terraform and OpenTofu: infrastructure configuration in HCL (`.tf`, `.tofu`, `.tfvars`), judged by the Terraform or
OpenTofu versions CI runs and by the tools CI runs on the configuration: `fmt`, `validate` and tflint, the
misconfiguration scanners, and `terraform test`.

A configuration has no build system: it is a directory of `.tf` files, and the project is one unit (a `modules/` child
is judged with the root that uses it). Its dependencies are the providers `required_providers` names (and the ones
`provider` blocks imply), which `terraform init` locks in `.terraform.lock.hcl`; what `init` downloads (`.terraform/`),
the state and plans are outputs that must never be committed: the state holds secrets.

The misconfiguration scanners (checkov, trivy, KICS, terrascan, tfsec) are both static analysis and security
scanning: their rules are what static analysis means for infrastructure code, so one of them in CI passes both checks.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping

from project_validator.ecosystems.model import Ecosystem, subcommands, toolchain_patterns
from project_validator.facts import Command, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Condition, Tool, combined, defined_by, either, starts, when

TERRAFORM = "Terraform"
TERRAFORM_LANGUAGE = frozenset({TERRAFORM})
CONFIGURATION_FILES = ("*.tf", "*.tofu")
# OpenTofu reads the same configuration with the same commands.
_CLI = ("terraform", "tofu")


def _commands(*words: str) -> tuple[tuple[str, ...], ...]:
    """`terraform <words>` and `tofu <words>`."""
    return tuple((cli, *words) for cli in _CLI)


# --- formatting

# `fmt -check` lists the files it would change and fails; plain `fmt` rewrites them. The pre-commit-terraform hook
# `terraform_fmt` rewrites them too.
TERRAFORM_FMT = format_tool(
    name="terraform fmt",
    languages=TERRAFORM_LANGUAGE,
    can={Enforcement.CHECK: "terraform fmt -check -recursive", Enforcement.APPLY: "terraform fmt -recursive"},
    formats=either(
        flagged(*_commands("fmt"), checks=("-check",)),
        flagged(("terraform_fmt",), checks=()),
    ),
    style=defined_by(),
)

# --- analysis

# `terraform validate` needs the providers `terraform init` (with `-backend=false`, no backend is needed) downloads;
# the run is counted as a claim, and a CI that forgets `init` fails on its own.
TERRAFORM_VALIDATE = analyzer(
    name="terraform validate",
    languages=TERRAFORM_LANGUAGE,
    how="terraform init -backend=false && terraform validate",
    analyses=when(starts(*_commands("validate"), ("terraform_validate",)), analysed),
)
TFLINT_SETTINGS = file_reader("tflint", (".tflint.hcl",))
# tflint has rules of its own without a configuration; `.tflint.hcl` enables the provider rulesets.
TFLINT = analyzer(
    name="tflint",
    languages=TERRAFORM_LANGUAGE,
    how="tflint (rulesets in .tflint.hcl)",
    analyses=when(starts(("tflint",), ("terraform_tflint",)), analysed),
    rules=defined_by(files=(TFLINT_SETTINGS.name,)),
)

# --- misconfiguration scanners: static analysis and security scanning at once

_TRIVY_FILESYSTEM = (("trivy", "fs"), ("trivy", "filesystem"), ("trivy", "repo"), ("trivy", "repository"))


def _trivy_misconfiguration(command: Command) -> bool:
    """`trivy config`, or a filesystem scan whose `--scanners` include misconfigurations (the pre-commit-terraform
    hook `terraform_trivy` runs one)."""
    argv = resolved(command)
    if starts_with(argv, ("trivy", "config"), ("terraform_trivy",)) is not None:
        return True
    if starts_with(argv, *_TRIVY_FILESYSTEM) is None:
        return False
    return any("misconfig" in value for value in option_values(argv, "--scanners"))


def _scanner(name: str, how: str, runs: Condition) -> Tool:
    """A misconfiguration scanner, which analyses the configuration and scans it for security problems."""
    return combined(
        analyzer(name=name, languages=TERRAFORM_LANGUAGE, how=how, analyses=when(runs, analysed)),
        scanner(name=name, languages=TERRAFORM_LANGUAGE, how=how, scans=when(runs, scanned)),
    )


MISCONFIGURATION_SCANNERS = (
    _scanner("checkov", "checkov -d .", starts(("checkov",), ("terraform_checkov",))),
    _scanner("trivy", "trivy config .", _trivy_misconfiguration),
    _scanner("KICS", "kics scan -p .", starts(("kics", "scan"))),
    _scanner("terrascan", "terrascan scan", starts(("terrascan", "scan"))),
    _scanner("tfsec", "tfsec . (now trivy)", starts(("tfsec",), ("terraform_tfsec",))),
)

CHECKOV_ACTION = Action(
    name="bridgecrewio/checkov-action", runs=lambda inputs: (("checkov", "-d", inputs.get("directory", ".")),)
)
_TRIVY_SCAN_TYPES = {"config": ("config",), "fs": ("fs",), "filesystem": ("fs",), "repo": ("repo",)}


def _trivy_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`aquasecurity/trivy-action`: `trivy <scan-type> [--scanners ...] <scan-ref>` (an image scan by default)."""
    words = _TRIVY_SCAN_TYPES.get(inputs.get("scan-type", "image"))
    if words is None:
        return ()
    scanners = (("--scanners", inputs["scanners"]),) if inputs.get("scanners") else ()
    return (("trivy", *words, *(word for pair in scanners for word in pair), inputs.get("scan-ref", ".")),)


TRIVY_ACTION = Action(name="aquasecurity/trivy-action", runs=_trivy_action)
KICS_ACTION = Action(
    name="checkmarx/kics-github-action",
    runs=lambda inputs: (("kics", "scan", "-p", *shlex.split(inputs.get("path", "."))),),
)
TERRASCAN_ACTION = Action(name="tenable/terrascan-action", runs=lambda _inputs: (("terrascan", "scan"),))
TFSEC_ACTION = Action(
    name="aquasecurity/tfsec-action", runs=lambda inputs: (("tfsec", inputs.get("working_directory", ".")),)
)

# --- tests

TERRAFORM_TEST_FILES = TestFiles(
    name="Terraform test files (*.tftest.hcl, *.tofutest.hcl)",
    languages=TERRAFORM_LANGUAGE,
    path=re.compile(r"\.(?:tftest|tofutest)\.hcl$"),
)
TERRAFORM_TEST = test_runner(
    name="terraform test",
    languages=TERRAFORM_LANGUAGE,
    how="terraform test",
    runs=when(starts(*_commands("test")), tested),
    tests=tests_of(TERRAFORM_TEST_FILES.name),
)

# --- dependencies: providers, locked by terraform init

PROVIDERS = "Terraform providers"
LOCKFILE = ".terraform.lock.hcl"
_DECLARES_PROVIDERS = re.compile(r"^\s*(?:required_providers\s*\{|provider\s+\")", re.MULTILINE)

PROVIDER_REQUIREMENTS = manifest_reader(
    name="Terraform provider requirements",
    manager=PROVIDERS,
    files=CONFIGURATION_FILES,
    declares=lambda _path, text: bool(_DECLARES_PROVIDERS.search(text)),
)
PROVIDER_LOCK = lockfile_reader(manager=PROVIDERS, files=(LOCKFILE,))
PROVIDERS_MANAGER = PackageManager(
    name=PROVIDERS,
    languages=TERRAFORM_LANGUAGE,
    lock_hint=f"commit {LOCKFILE}, which terraform init writes with the version and hashes of every provider",
)

# --- outputs: what init downloads, the state and plans

INIT_DIRECTORY = BuildOutput(
    languages=TERRAFORM_LANGUAGE,
    name="the .terraform directory",
    globs=ignored_at_top_level(r"\.terraform"),
    paths=directories(".terraform"),
    hint="ignore .terraform/, the providers and modules terraform init downloads",
    artifacts=(".terraform/",),
)
STATE_AND_PLANS = BuildOutput(
    languages=TERRAFORM_LANGUAGE,
    name="Terraform state, plans and crash logs",
    globs=ignored_at_top_level(r"\*\.tfstate(?:\.\*)?|\*\.tfplan|crash\.log|crash\.\*\.log"),
    paths=("terraform.tfstate", "terraform.tfstate.backup", "plan.tfplan", "crash.log"),
    hint="ignore *.tfstate, *.tfstate.*, *.tfplan and crash.log: the state holds secrets and belongs in a remote "
    "backend",
    artifacts=("*.tfstate", "*.tfstate.*", "*.tfplan", "crash.log", "crash.*.log"),
)

# --- recognition

# What shows a CI job works on the configuration, besides running terraform or tofu.
# The linters and scanners that read Terraform without running it.
CI_PROGRAMS = (("tflint",), ("checkov",), ("tfsec",), ("terrascan",), ("kics",), ("trivy", "config"))
_VERBS = ("init", "validate", "plan", "apply", "fmt", "test")

TERRAFORM_ECOSYSTEM = Ecosystem(
    label=TERRAFORM,
    languages=TERRAFORM_LANGUAGE,
    source_suffixes={".tf": TERRAFORM, ".tofu": TERRAFORM, ".tfvars": TERRAFORM},
    # HCL is also Packer's and Nomad's; in a Terraform project, `.hcl` files are its tests and its lockfile.
    ambiguous_suffixes={".hcl": TERRAFORM},
    ci_programs=CI_PROGRAMS,
    # `hashicorp/setup-terraform` takes `terraform_version`, `opentofu/setup-opentofu` `tofu_version`; the images are
    # `hashicorp/terraform:1.9.8` and `ghcr.io/opentofu/opentofu:1.8.0`.
    toolchain=toolchain_patterns(
        TERRAFORM,
        inputs=("terraform_version", "tofu_version"),
        images=("hashicorp/terraform", "ghcr.io/opentofu/opentofu"),
        programs=(*subcommands("terraform", *_VERBS), *subcommands("tofu", *_VERBS)),
        setup=("terraform", "opentofu"),
    ),
)
TERRAFORM_VERSIONS = versions_axis("Terraform version", TERRAFORM, TERRAFORM_LANGUAGE)
