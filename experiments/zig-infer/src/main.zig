const std = @import("std");

pub fn main() !void {
    const stdout = std.io.getStdOut().writer();
    try stdout.print("noxinf stub (replace with GGUF loader and sampler)\n", .{});
}
