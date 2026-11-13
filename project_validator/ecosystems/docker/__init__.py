"""Docker: Dockerfiles (`Dockerfile`, `Containerfile`, `Dockerfile.<stage>`, `<name>.Dockerfile`), a format. A
Dockerfile is not a program, and what is asked of it is hygiene: it parses (`data-wellformed`: known instructions, a
`FROM` first; `dockerfile.py`), hadolint lints it (`static-analysis`, and `security-scanning` with its security rules,
beside the misconfiguration scanners checkov, trivy and KICS), and CI scans the image it builds for vulnerable packages
(`dependency-audit`: trivy, grype, Docker Scout; `tools.py`). Compose files are YAML, the Data format's. The build
itself (`docker build`, `docker/build-push-action`) is what shows a CI job works with the ecosystem; nothing yet
asks that an image is built or smoke-tested, nor that `.dockerignore` exists."""

from __future__ import annotations

import re

from project_validator.ecosystems.model import Ecosystem

DOCKERFILE = "Dockerfile"
DOCKERFILE_ONLY = frozenset({DOCKERFILE})

DOCKER = Ecosystem(
    label="Docker",
    kind="format",
    languages=DOCKERFILE_ONLY,
    source_suffixes={".Dockerfile": DOCKERFILE, ".dockerfile": DOCKERFILE},
    source_names={"Dockerfile": DOCKERFILE, "Containerfile": DOCKERFILE, "Dockerfile.*": DOCKERFILE},
    ci_programs=(
        ("docker", "build"),
        ("docker", "buildx", "build"),
        ("docker", "compose"),
        ("podman", "build"),
        ("buildah", "build"),
        ("buildah", "bud"),
        ("hadolint",),
        ("trivy", "image"),
    ),
    # The actions that build an image, or set its builder up, in a job's evidence.
    ci_usage=re.compile(r"(?<![\w-])(?:build-push-action|setup-buildx-action|setup-docker-action|bake-action)\b"),
)
