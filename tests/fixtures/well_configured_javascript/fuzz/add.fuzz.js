import { add } from "../src/add.js";

/** Jazzer.js entry point: adding any input length must not throw. */
export function fuzz(data) {
  add(data.length, data.length);
}
