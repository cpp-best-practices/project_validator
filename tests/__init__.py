"""The test suite: offline, so that what it records never depends on the network or the user's tokens."""

from __future__ import annotations

import os

# The source-control host is never asked (see `project_validator.hosting`); its tests stand a fake host in.
os.environ.setdefault("PROJECT_VALIDATOR_OFFLINE", "1")
