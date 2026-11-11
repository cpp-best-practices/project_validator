const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    // Release builds keep the safety checks unless asked otherwise.
    const optimize = b.standardOptimizeOption(.{ .preferred_optimize_mode = .ReleaseSafe });

    const shop = b.addModule("shop", .{ .root_source_file = b.path("src/shop.zig") });

    const exe = b.addExecutable(.{
        .name = "shop",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addImport("shop", shop);
    b.installArtifact(exe);

    const tests = b.addTest(.{
        .root_source_file = b.path("src/shop.zig"),
        .target = target,
        .optimize = optimize,
    });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run the unit tests");
    test_step.dependOn(&run_tests.step);
}
