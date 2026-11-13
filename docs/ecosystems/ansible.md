# Ansible

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
units`) runs.

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
