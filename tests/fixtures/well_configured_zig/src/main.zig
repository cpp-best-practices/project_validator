const std = @import("std");
const shop = @import("shop");

pub fn main() void {
    std.debug.print("{d}\n", .{shop.total(&.{ 1, 2, 3 })});
}
