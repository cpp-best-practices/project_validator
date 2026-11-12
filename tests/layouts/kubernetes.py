"""Kinds of Kubernetes project, for tests that run a check in every layout: manifests in a directory of them."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shop
spec:
  replicas: 2
  selector:
    matchLabels:
      app: shop
  template:
    metadata:
      labels:
        app: shop
    spec:
      containers:
        - name: shop
          image: ghcr.io/example/shop:1.0.0
"""

LAYOUTS = (
    ProjectLayout(
        name="Kubernetes manifests",
        files={"k8s/deployment.yaml": MANIFEST},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Kubernetes", "YAML"}),
    ),
)
