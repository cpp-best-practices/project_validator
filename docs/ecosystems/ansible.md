# Ansible

Learn more: [Ansible](https://docs.ansible.com/).

A format, recognised by content: a collection (`galaxy.yml`), a role (`meta/main.yml` with `galaxy_info`), an
`ansible.cfg`, a molecule scenario (`molecule/<scenario>/molecule.yml`), or a playbook (YAML whose plays name
`hosts` and `tasks` or `roles`). Its files are YAML, the Data format's, so `data-wellformed` judges them as YAML; a
role's `templates/` are templates, noted and not parsed; its Jinja templates (`.j2`) belong to it without being a
format of their own.

A CI job works with the ecosystem when it runs `ansible`, `ansible-playbook`, `ansible-galaxy`, `ansible-lint`,
`ansible-test` or `molecule`, or the `ansible/ansible-lint` action.

## `tests-run`

molecule scenarios (`molecule/<scenario>/molecule.yml`) that `molecule test` runs, or a collection's integration
targets (`tests/integration/targets/<target>/tasks/main.yml`) that `ansible-test integration` (or `ansible-test
units`) runs. A scenario whose verifier is testinfra (`verifier: name: testinfra`) has Python tests
(`molecule/<scenario>/tests/test_*.py`): `molecule test` runs them, which is the Python profile's tests-run.

antsibull-nox, the ansible-collections organisation's CI driver: `nox` (or antsibull-nox's reusable workflow,
`ansible-community/antsibull-nox/.github/workflows/reusable-nox-matrix.yml`) runs the sessions `antsibull-nox.toml`
configures, or those `nox -e` names: `ansible_test_sanity`, `ansible_test_units` and `ansible_test_integration` run
`ansible-test`, `ansible_lint` runs ansible-lint, and the `lint` session's switches (`run_ruff_check`,
`run_ruff_format`, `run_black`, `run_isort`, `run_flake8`, `run_pylint`, `run_yamllint`, `run_mypy`) run those tools.

## `static-analysis`

ansible-lint (`ansible-lint`, or the `ansible/ansible-lint` and `ansible-community/ansible-lint-action` actions),
with its settings in `.ansible-lint` or `.config/ansible-lint.yml`; checkov (`checkov -d . --framework ansible`) and
KICS, which read Ansible too.

## `security-scanning`

ansible-lint's security rules (`risky-shell-pipe`, `no-log-password`, `risky-file-permissions`), or checkov
(`bridgecrewio/checkov-action`) or KICS (`checkmarx/kics-github-action`).

## Not judged

ansible-lint's `production` profile (or `--strict`) would be warnings as errors, a compiled language's practice;
yamllint lints the YAML, which is the Data format's to ask for; the target platforms (molecule platforms, a matrix of
distributions) and ansible-core versions would be a platform axis, which a format has no toolchain to carry. The
other checks have no tool for playbooks and are skipped.
