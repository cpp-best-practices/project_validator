import { add } from "../src/add.js";

/** Jazzer.js entry point: adding any input length must not throw. */
export function fuzz(data: Buffer): void {
  add(data.length, data.length);
}
