"""The Ansible profile: a format recognised by content, whose files are YAML; its tests, lint and policy scanners."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.ansible import ANSIBLE_ECOSYSTEM
from tests.layouts.ansible import PLAYBOOK
from tests.support import GITHUB_WORKFLOW, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Ansible playbook"
SCENARIO = {"molecule/default/molecule.yml": "driver:\n  name: docker\nplatforms:\n  - name: debian\n"}
TARGET = {"tests/integration/targets/shop/tasks/main.yml": "- name: Check\n  ansible.builtin.ping:\n"}
ROLE_META = "galaxy_info:\n  author: shop\n  license: MIT\n  min_ansible_version: '2.15'\n"
INGRESS = "apiVersion: networking.k8s.io/v1\nkind: Ingress\nspec:\n  tls:\n    - hosts:\n        - shop.example.com\n"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _action(uses: str) -> dict[str, str]:
    steps = [{"uses": uses}]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": steps}}})}


class RecognitionTests(unittest.TestCase):
    def test_collections_roles_configuration_scenarios_and_playbooks_are_the_format(self) -> None:
        recognised = (
            {"galaxy.yml": "namespace: shop\nname: web\nversion: 1.0.0\n"},
            {"ansible.cfg": "[defaults]\ninventory = hosts\n"},
            {"roles/shop/meta/main.yml": ROLE_META},
            SCENARIO,
            {"site.yml": PLAYBOOK},
            {"playbooks/web.yaml": "- hosts: web\n  roles:\n    - shop\n"},
        )
        for files in recognised:
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, frozenset())
                self.assertIn("Ansible", structure.formats)
                self.assertEqual(structure.recognised_by["Ansible"], ("content",))
        not_recognised = (
            {"roles/shop/meta/main.yml": "dependencies: []\n"},
            {"inventory/hosts.yml": "all:\n  hosts:\n    shop.example.com:\n"},
            {"k8s/ingress.yaml": INGRESS},
            {".github/workflows/ci.yml": "on: push\njobs: {}\n"},
        )
        for files in not_recognised:
            with self.subTest(files=files), temp_project(files) as root:
                self.assertNotIn("Ansible", make_context(root).structure.formats)

    def test_jinja_templates_are_accounted_for(self) -> None:
        files = {"site.yml": PLAYBOOK, "roles/shop/templates/shop.conf.j2": "port = {{ shop_port }}\n"}
        with temp_project(files) as root:
            self.assertEqual(make_context(root).structure.unrecognised_suffixes, ())
        self.assertEqual((ANSIBLE_ECOSYSTEM.kind, ANSIBLE_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in ("ansible-lint", "molecule test", "ansible-playbook site.yml", "uses: ansible/ansible-lint@v24"):
            with self.subTest(text=text):
                self.assertTrue(uses(ANSIBLE_ECOSYSTEM, text))
        for text in ("npm test", "helm lint charts/shop"):
            with self.subTest(text=text):
                self.assertFalse(uses(ANSIBLE_ECOSYSTEM, text))


class AnsibleTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_molecule_and_ansible_test_run_the_scenarios_and_targets(self) -> None:
        cases = (
            ({**SCENARIO, **_ci("molecule test")}, Status.PASS),
            ({**SCENARIO, **_ci("molecule test --all")}, Status.PASS),
            ({**TARGET, **_ci("ansible-test integration --docker")}, Status.PASS),
            ({**TARGET, **_ci("ansible-test units")}, Status.PASS),
            ({**SCENARIO, **_ci("ansible-lint")}, Status.WARN),
            (_ci("molecule test"), Status.FAIL),
        )
        for files, status in cases:
            with self.subTest(files=files):
                self.assertEqual(self._run(tests_run, files).status, status)

    def test_ansible_lint_lints_and_scans_and_the_misconfiguration_scanners_do_both(self) -> None:
        for files, tool in (
            (_ci("ansible-lint --profile production"), "ansible-lint"),
            (_action("ansible/ansible-lint@v24"), "ansible-lint"),
            (_action("ansible-community/ansible-lint-action@v6"), "ansible-lint"),
            (_ci("checkov -d . --framework ansible"), "checkov"),
            (_ci("kics scan -p ."), "KICS"),
        ):
            expected = (f"{tool} runs", f"CI scans the code for security problems with {tool}")
            with self.subTest(files=files):
                results = (self._run(static_analysis, files), self._run(security_scanning, files))
                self.assertEqual(tuple(result.status for result in results), (Status.PASS, Status.PASS))
                self.assertEqual(tuple(result.message for result in results), expected)
        for path in (".ansible-lint", ".config/ansible-lint.yml"):
            configured = {path: "profile: production\n", **_ci("ansible-lint")}
            with self.subTest(path=path):
                self.assertEqual(self._run(static_analysis, configured), Result.passed(f"ansible-lint ({path}) runs"))
        # trivy does not read Ansible; running a playbook is not linting it.
        for line in ("trivy config .", "ansible-playbook site.yml"):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)).status, Status.FAIL)
