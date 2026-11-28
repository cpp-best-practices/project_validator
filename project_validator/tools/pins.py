"""The versions the project's files pin its tools at, read as `PinnedTool` facts (upstream #412): pre-commit's hooks
at their repository's `rev:` (or the version a `# frozen:` comment names beside a commit), exact requirements in a
requirements file, and exact dependencies in package.json."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from project_validator import yaml_support
from project_validator.facts import Fact, Origin
from project_validator.facts.pins import PinnedTool, exact
from project_validator.facts.settings import SettingsReader

# `rev: 0123abcd...  # frozen: v1.2.3`: a commit, and the tag it is.
_FROZEN = re.compile(r"rev:\s*['\"]?(?P<rev>[0-9a-f]{7,40})['\"]?\s*#\s*frozen:\s*(?P<version>\S+)")
_REQUIREMENT = re.compile(r"^\s*(?P<package>[A-Za-z0-9][\w.-]*)(?:\[[^\]]*\])?\s*==\s*(?P<version>[^\s;#]+)", re.M)


def _pre_commit(path: str, text: str) -> Iterator[Fact]:
    try:
        config = yaml_support.load(text)
    except yaml_support.YamlError:
        return
    repos = config.get("repos") if isinstance(config, dict) else None
    frozen = {found["rev"]: found["version"] for found in _FROZEN.finditer(text)}
    for repo in repos if isinstance(repos, list) else ():
        if not isinstance(repo, dict) or not isinstance(hooks := repo.get("hooks"), list):
            continue
        rev = str(repo.get("rev", ""))
        version = exact(frozen.get(rev, rev))
        for hook in hooks if version else ():
            if isinstance(hook, dict) and hook.get("id"):
                yield PinnedTool(origin=Origin(path=path), package=str(hook["id"]), version=version)


def _requirements(path: str, text: str) -> Iterator[Fact]:
    for found in _REQUIREMENT.finditer(text):
        if version := exact(found["version"]):
            yield PinnedTool(origin=Origin(path=path), package=found["package"], version=version)


def _package_json(path: str, text: str) -> Iterator[Fact]:
    try:
        manifest = json.loads(text)
    except ValueError:
        return
    for table in ("devDependencies", "dependencies") if isinstance(manifest, dict) else ():
        listed = manifest.get(table)
        for package, written in listed.items() if isinstance(listed, dict) else ():
            if isinstance(written, str) and (version := exact(written)) and not written.startswith("v"):
                yield PinnedTool(origin=Origin(path=path), package=package, version=version)


PRE_COMMIT_PINS = SettingsReader(
    name="pre-commit pins", files=(".pre-commit-config.yaml", ".pre-commit-config.yml"), read=_pre_commit
)
REQUIREMENT_PINS = SettingsReader(
    name="requirement pins", files=("*requirements*.txt", "requirements/*.txt"), read=_requirements
)
PACKAGE_JSON_PINS = SettingsReader(name="package.json pins", files=("package.json",), read=_package_json)
