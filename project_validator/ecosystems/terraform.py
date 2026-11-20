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
from collections.abc import Callable, Mapping

from project_validator.core import Context
from project_validator.ecosystems.model import Ecosystem, subcommands, toolchain_patterns
from project_validator.facts import Command, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Launched
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, either, starts, when
from project_validator.tools.misconfiguration import misconfiguration_scanner, misconfiguration_scanners

TERRAFORM = "Terraform"
TERRAFORM_LANGUAGE = frozenset({TERRAFORM})
CONFIGURATION_FILES = ("*.tf", "*.tofu")
# OpenTofu reads the same configuration with the same commands.
_CLI = ("terraform", "tofu")


def _commands(*words: str) -> tuple[tuple[str, ...], ...]:
    """`terraform <words>` and `tofu <words>`."""
    return tuple((cli, *words) for cli in _CLI)


# `terraform -chdir=infra validate`: the global option before the subcommand changes the directory it runs in.
def _chdir(command: Command, _context: Context) -> list[Expansion] | None:
    argv = resolved(command)
    if len(argv) < 3 or argv[0] not in _CLI or not argv[1].startswith("-chdir="):
        return None
    return [Launched(argv=(argv[0], *argv[2:]))]


CHDIR = CommandExpander(name="terraform -chdir", expand=_chdir)


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

# --- misconfiguration scanners: static analysis and security scanning at once (see
# `project_validator.tools.misconfiguration`), with the pre-commit-terraform hooks that run them

MISCONFIGURATION_SCANNERS = (
    *misconfiguration_scanners(TERRAFORM_LANGUAGE, checkov=(("terraform_checkov",),), trivy=(("terraform_trivy",),)),
    misconfiguration_scanner("terrascan", TERRAFORM_LANGUAGE, "terrascan scan", starts(("terrascan", "scan"))),
    misconfiguration_scanner(
        "tfsec", TERRAFORM_LANGUAGE, "tfsec . (now trivy)", starts(("tfsec",), ("terraform_tfsec",))
    ),
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

# clowdhaus/terraform-min-max's outputs: the oldest and the latest Terraform the `required_version` constraint allows.
_MIN_MAX = re.compile(r"\$\{\{\s*steps\.[\w-]+\.outputs\.(minVersion|maxVersion)\s*\}\}")
_MIN_MAX_LABELS = {"minVersion": "oldest required_version", "maxVersion": "latest required_version"}


def _version_input(name: str) -> Callable[[Mapping[str, str]], str | None]:
    """A setup action's version input `name`: a terraform-min-max output as what it stands for; another expression is
    left to the patterns."""

    def read(inputs: Mapping[str, str]) -> str | None:
        value = inputs.get(name, "")
        if (found := _MIN_MAX.fullmatch(value.strip())) is not None:
            return _MIN_MAX_LABELS[found[1]]
        return None

    return read


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
        steps=(
            ("hashicorp/setup-terraform", _version_input("terraform_version")),
            ("clowdhaus/terraform-composite-actions/pre-commit", _version_input("terraform-version")),
        ),
    ),
)
TERRAFORM_VERSIONS = versions_axis("Terraform version", TERRAFORM, TERRAFORM_LANGUAGE)
