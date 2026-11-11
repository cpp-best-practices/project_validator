//! Prices of the shop's items.
const std = @import("std");

/// The sum of `prices`.
pub fn total(prices: []const u32) u32 {
    var sum: u32 = 0;
    for (prices) |price| sum += price;
    return sum;
}

/// `price` with `percent` taken off; a percentage of zero changes nothing.
pub fn discounted(price: u32, percent: u32) u32 {
    if (percent == 0) return price;
    return price - price * percent / 100;
}

test "total sums the prices" {
    try std.testing.expectEqual(@as(u32, 6), total(&.{ 1, 2, 3 }));
    try std.testing.expectEqual(@as(u32, 0), total(&.{}));
}

test "discounted takes the percentage off" {
    try std.testing.expectEqual(@as(u32, 90), discounted(100, 10));
    try std.testing.expectEqual(@as(u32, 100), discounted(100, 0));
}
