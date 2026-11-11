"""Kinds of Zig project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

MAIN = 'const std = @import("std");\n\npub fn main() void {\n    std.debug.print("shop\\n", .{});\n}\n'

LAYOUTS = (
    ProjectLayout(
        name="Zig build",
        files={
            "build.zig": 'const std = @import("std");\n\npub fn build(b: *std.Build) void {\n'
            '    const exe = b.addExecutable(.{ .name = "shop", .root_source_file = b.path("src/main.zig"), '
            ".target = b.standardTargetOptions(.{}), .optimize = b.standardOptimizeOption(.{}) });\n"
            "    b.installArtifact(exe);\n}\n",
            "src/main.zig": MAIN,
        },
        languages=frozenset({"Zig"}),
        build_systems=frozenset({"Zig build"}),
    ),
    ProjectLayout(
        name="Zig sources",
        files={"src/main.zig": MAIN},
        languages=frozenset({"Zig"}),
        build_systems=frozenset(),
        # Without a build.zig there is no executable to harden.
        skipped=frozenset({"hardening"}),
    ),
)
