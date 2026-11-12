# Docker

A format: Dockerfiles, recognised by name (`Dockerfile`, `Containerfile`, `Dockerfile.<stage>`) or by suffix
(`<name>.Dockerfile`, `<name>.dockerfile`). A Dockerfile is not a program, so nothing about toolchains, tests or
coverage applies; what is asked of it is hygiene. Compose files are YAML, and the Data format's. A CI job works with
the ecosystem when it builds an image (`docker build`, `docker buildx build`, `podman build`, `buildah`,
`docker/build-push-action`) or runs one of the tools below.

## `data-wellformed`

Every Dockerfile parses: it has instructions, each a known one (`FROM`, `RUN`, `COPY`, `ARG`, …) with arguments, and
the first instruction that is not an `ARG` is a `FROM`. Comments, line continuations (with the character the
`# escape=` directive sets), and heredocs (`RUN <<EOF … EOF`) are read as BuildKit reads them.

## `static-analysis`

hadolint (`hadolint Dockerfile`, or `hadolint/hadolint-action`), with its settings in `.hadolint.yaml` or the file
`--config` names. The misconfiguration scanners count too: checkov, `trivy config` (or a `trivy fs` whose `--scanners`
include misconfigurations), KICS.

## `security-scanning`

hadolint's security rules (a non-root `USER`, pinned versions, no `latest` tag), or one of the misconfiguration
scanners: checkov (`bridgecrewio/checkov-action`), `trivy config` (`aquasecurity/trivy-action` with
`scan-type: config`), KICS (`checkmarx/kics-github-action`).

## `dependency-audit`

CI scans the image it builds for vulnerable packages: `trivy image <image>` (or `aquasecurity/trivy-action`, which
scans an image unless told otherwise), `grype <image>` (or `anchore/scan-action`), `docker scout cves <image>` (or
`docker/scout-action`).

## Not judged

Whether CI builds the image, or smoke-tests it (`container-structure-test`), is not a `tests-run` for a format;
whether `.dockerignore` exists is not a `vcs-ignore`; and whether base images are pinned by digest is a dependency
rule (#24) a later check asks. The other checks have no tool for Dockerfiles and are skipped.
