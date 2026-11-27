// What the tests read of this checkout: its root, and the HTML report its Python package writes.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** The validator's HTML report on a fixture, written by the Python package of this checkout ($PYTHON, else python3). */
export function report(fixture = "bare_python") {
  const python = process.env.PYTHON || "python3";
  const args = ["-m", "project_validator", "--format", "html", "--offline", `tests/fixtures/${fixture}`];
  const done = spawnSync(python, args, { cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (!done.stdout.startsWith("<!DOCTYPE html>")) throw new Error(`no report from ${python}: ${done.stderr}`);
  return done.stdout;
}
