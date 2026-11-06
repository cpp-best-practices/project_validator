import { expect, test } from "vitest";

import { add } from "./add.js";

test("adds", () => {
  expect(add(1, 2)).toBe(3);
});
