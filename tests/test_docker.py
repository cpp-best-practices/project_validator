"""The Docker profile: a format ecosystem of Dockerfiles, with a parser, hadolint, the misconfiguration scanners and
the auditors of the image CI builds."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import claim_conflicts
from project_validator.ecosystems.docker import DOCKER
from project_validator.ecosystems.docker.dockerfile import DOCKERFILE_PARSER, Instruction, instructions
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.wellformed import ParseError
from tests.support import GITHUB_WORKFLOW, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Dockerfile"
FROM = "FROM alpine:3.20\n"
DOCKERFILE = """\
# syntax=docker/dockerfile:1
# The base image.
FROM nginx:1.27-alpine AS serve

COPY site/ /usr/share/nginx/html/
RUN apk add --no-cache \\
    # a comment inside the continuation
    curl \\
    wget
RUN <<EOF
set -eu
chown -R nginx:nginx /usr/share/nginx/html
EOF
USER nginx
expose 8080
"""


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _action(uses: str, **inputs: str) -> dict[str, str]:
    """A workflow whose one job uses `uses` with `inputs`."""
    steps = [{"uses": uses, "with": inputs}]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": steps}}})}


def _problem(text: str) -> tuple[str, int | None]:
    try:
        DOCKERFILE_PARSER.parse("Dockerfile", text.encode())
    except ParseError as error:
        return error.message, error.line
    return "", None


class RecognitionTests(unittest.TestCase):
    def test_dockerfiles_by_name_and_by_suffix_are_the_format(self) -> None:
        files = {
            "Dockerfile": FROM,
            "deploy/Containerfile": FROM,
            "Dockerfile.dev": FROM,
            "build/app.Dockerfile": FROM,
            # A different base name: on a case-insensitive file system, app.dockerfile would be the file above.
            "build/web.dockerfile": FROM,
            "compose.yaml": "services: {}\n",
        }
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.formats), (frozenset(), frozenset({"Dockerfile", "YAML"})))
        signals = (
            ".Dockerfile files",
            ".dockerfile files",
            "Containerfile files",
            "Dockerfile files",
            "Dockerfile.* files",
        )
        self.assertEqual(structure.recognised_by["Docker"], signals)
        self.assertEqual(structure.unrecognised_suffixes, ())
        self.assertEqual((DOCKER.kind, DOCKER.toolchain, DOCKER.build_systems), ("format", None, ()))

    def test_ci_usage(self) -> None:
        used = ("docker build -t app .", "docker buildx build .", "podman build .", "hadolint Dockerfile")
        for text in (*used, "uses: docker/build-push-action@v6", "trivy image app:ci"):
            with self.subTest(text=text):
                self.assertTrue(uses(DOCKER, text))
        for text in ("npm test", "docker run app", "trivy fs ."):
            with self.subTest(text=text):
                self.assertFalse(uses(DOCKER, text))


class ParserTests(unittest.TestCase):
    def test_instructions_are_read_as_buildkit_reads_them(self) -> None:
        found = list(instructions(DOCKERFILE))
        self.assertEqual(
            found,
            [
                Instruction(line=3, keyword="FROM", arguments="nginx:1.27-alpine AS serve"),
                Instruction(line=5, keyword="COPY", arguments="site/ /usr/share/nginx/html/"),
                Instruction(line=6, keyword="RUN", arguments="apk add --no-cache curl wget"),
                Instruction(line=10, keyword="RUN", arguments="<<EOF"),
                Instruction(line=14, keyword="USER", arguments="nginx"),
                Instruction(line=15, keyword="EXPOSE", arguments="8080"),
            ],
        )

    def test_the_escape_directive_and_quoted_heredocs(self) -> None:
        text = "# escape=`\nFROM a\nRUN echo `\n  hi\nCOPY <<-'EOT' <<\"EOU\" /x\n  one\nEOT\ntwo\nEOU\nCMD run\n"
        found = [(instruction.keyword, instruction.arguments) for instruction in instructions(text)]
        self.assertEqual(found, [("FROM", "a"), ("RUN", "echo hi"), ("COPY", "<<-'EOT' <<\"EOU\" /x"), ("CMD", "run")])
        # A heredoc never closed, or a continuation on the last line, runs to the end of the file.
        self.assertEqual([i.keyword for i in instructions("FROM a\nRUN <<EOF\necho\n")], ["FROM", "RUN"])
        self.assertEqual([i.arguments for i in instructions("FROM a\nRUN echo \\\n")], ["a", "echo"])

    def test_well_formed_dockerfiles_and_the_problems_found(self) -> None:
        for text in (DOCKERFILE, FROM, "ARG VERSION=3.20\nFROM alpine:$VERSION\n", "from alpine\n"):
            with self.subTest(text=text):
                self.assertEqual(_problem(text), ("", None))
        problems = (
            ("", "no instructions: a Dockerfile starts with FROM", None),
            ("# only a comment\n\n", "no instructions: a Dockerfile starts with FROM", None),
            ("FROM\n", "FROM has no arguments", 1),
            ("RUN apk add curl\nFROM alpine\n", "the first instruction is RUN, not FROM", 1),
            ("FROM alpine\n\nFOO bar\n", "unknown instruction FOO", 3),
            ("ARG VERSION=1\n", "no build stage: a Dockerfile needs a FROM", 1),
        )
        for text, message, line in problems:
            with self.subTest(text=text):
                self.assertEqual(_problem(text), (message, line))
        with self.assertRaises(ParseError):
            DOCKERFILE_PARSER.parse("Dockerfile", b"\xff\xfe")


class DockerTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_every_dockerfile_must_parse(self) -> None:
        self.assertEqual(self._run(data_wellformed, {}), Result.passed("1 Dockerfile file parses"))
        result = self._run(data_wellformed, {"Dockerfile": "RUN apk add curl\nFROM alpine\n"})
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("Dockerfile:1:1: the first instruction is RUN, not FROM", result.details)

    def test_hadolint_lints_and_its_security_rules_scan(self) -> None:
        for files in (_ci("hadolint Dockerfile"), _action("hadolint/hadolint-action@v3")):
            with self.subTest(files=files):
                self.assertEqual(self._run(static_analysis, files), Result.passed("hadolint runs"))
                result = self._run(security_scanning, files)
                self.assertEqual(
                    (result.status, result.message),
                    (Status.PASS, "CI scans the code for security problems with hadolint"),
                )
        configured = {".hadolint.yaml": "ignored: [DL3018]\n", **_ci("hadolint Dockerfile")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("hadolint (.hadolint.yaml) runs"))
        named = {"ci/hadolint.yaml": "ignored: []\n", **_ci("hadolint --config ci/hadolint.yaml Dockerfile")}
        self.assertEqual(self._run(static_analysis, named), Result.passed("hadolint (ci/hadolint.yaml) runs"))
        by_action = {"ci/hadolint.yaml": "", **_action("hadolint/hadolint-action@v3", config="ci/hadolint.yaml")}
        self.assertEqual(self._run(static_analysis, by_action), Result.passed("hadolint (ci/hadolint.yaml) runs"))
        self.assertEqual(self._run(static_analysis, _ci("docker build .")).status, Status.FAIL)

    def test_the_misconfiguration_scanners_analyse_and_scan(self) -> None:
        for files in (
            _ci("checkov -d ."),
            _ci("trivy config ."),
            _ci("trivy fs --scanners misconfig,vuln ."),
            _ci("kics scan -p ."),
            _action("aquasecurity/trivy-action@0.30.0", **{"scan-type": "config", "scan-ref": "."}),
            _action("bridgecrewio/checkov-action@v12"),
            _action("checkmarx/kics-github-action@v2"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(static_analysis, files).status, Status.PASS)
                self.assertEqual(self._run(security_scanning, files).status, Status.PASS)
        self.assertEqual(self._run(security_scanning, _ci("trivy fs .")).status, Status.WARN)

    def test_the_image_is_audited_for_vulnerable_packages(self) -> None:
        for line, tool in (
            ("trivy image --exit-code 1 shop:ci", "trivy"),
            ("trivy i shop:ci", "trivy"),
            ("grype shop:ci", "grype"),
            ("docker scout cves shop:ci", "Docker Scout"),
        ):
            with self.subTest(line=line):
                expected = Result.passed(f"CI audits the dependencies with {tool}")
                self.assertEqual(self._run(dependency_audit, _ci("docker build -t shop:ci .", line)), expected)
        for files, tool in (
            (_action("aquasecurity/trivy-action@0.30.0", **{"image-ref": "shop:ci"}), "trivy"),
            (_action("anchore/scan-action@v6", image="shop:ci"), "grype"),
            (_action("docker/scout-action@v1", command="cves,recommendations", image="shop:ci"), "Docker Scout"),
        ):
            with self.subTest(files=files):
                self.assertEqual(
                    self._run(dependency_audit, files), Result.passed(f"CI audits the dependencies with {tool}")
                )
        for files in (_ci("trivy fs ."), _action("aquasecurity/trivy-action@0.30.0", **{"scan-type": "k8s"})):
            with self.subTest(files=files):
                self.assertEqual(self._run(dependency_audit, files).status, Status.WARN)


class SourceNameTests(unittest.TestCase):
    def test_a_source_name_is_claimed_by_one_ecosystem(self) -> None:
        other = Ecosystem(label="Other", languages=frozenset({"Other"}), source_names={"Dockerfile": "Other"})
        self.assertEqual(
            claim_conflicts([DOCKER, other]), ["Other: source name Dockerfile is already claimed by Docker"]
        )
        self.assertEqual(claim_conflicts([DOCKER, Ecosystem(label="O", languages=frozenset({"O"}))]), [])
