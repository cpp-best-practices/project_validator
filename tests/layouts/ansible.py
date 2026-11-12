"""Kinds of Ansible project, for tests that run a check in every layout: a playbook."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

PLAYBOOK = """\
- name: Deploy the shop
  hosts: all
  become: true
  tasks:
    - name: Install the package
      ansible.builtin.apt:
        name: shop
        state: present
"""

LAYOUTS = (
    ProjectLayout(
        name="Ansible playbook",
        files={"playbooks/site.yml": PLAYBOOK},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Ansible", "YAML"}),
    ),
)
