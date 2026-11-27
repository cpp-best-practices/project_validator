// The validator's Web Worker (web/worker.js): Pyodide stood in for by a file system in memory and a validator that
// reports what it was given, the worker's globals by a context of its own.
import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";
import { run, settled } from "./load.mjs";

/**
 * Pyodide's file system (Emscripten's), as much of it as the worker uses, and as strict: directories (null) and files
 * in a map of paths; what Emscripten refuses (a file in no directory, a directory removed while it holds anything,
 * reading what is not there) throws.
 */
function fileSystem() {
  const nodes = new Map([["/", null]]);
  const parent = (path) => path.slice(0, path.lastIndexOf("/")) || "/";
  const isDirectory = (path) => nodes.has(path) && nodes.get(path) === null;
  const entries = (path) => [...nodes.keys()].filter((key) => key !== "/" && key !== path && parent(key) === path);
  const file = (path) => (isDirectory(parent(path)) ? path : refuse("ENOENT", parent(path)));
  return {
    nodes,
    mkdirTree: (path) => directories(path).forEach((directory) => makeDirectory(nodes, directory, isDirectory)),
    writeFile: (path, bytes) => (isDirectory(path) ? refuse("EISDIR", path) : nodes.set(file(path), bytes)),
    truncate: (path, size) => (nodes.has(path) ? nodes.set(path, new Uint8Array(size)) : refuse("ENOENT", path)),
    analyzePath: (path) => ({ exists: nodes.has(path) }),
    readdir: (path) =>
      isDirectory(path)
        ? [".", "..", ...entries(path).map((key) => key.slice(path.length + 1))]
        : refuse("ENOTDIR", path),
    stat: (path) => (nodes.has(path) ? { mode: isDirectory(path) ? 0o40000 : 0o100000 } : refuse("ENOENT", path)),
    isDir: (mode) => mode === 0o40000,
    rmdir: (path) => (entries(path).length || !isDirectory(path) ? refuse("ENOTEMPTY", path) : nodes.delete(path)),
    unlink: (path) => (isDirectory(path) ? refuse("EISDIR", path) : nodes.delete(path)),
  };
}

function refuse(what, path) {
  throw new Error(`${what}: ${path}`);
}

/** `/a/b/c` is `/a`, `/a/b` and `/a/b/c`. */
function directories(path) {
  const parts = path.split("/").filter(Boolean);
  return parts.map((_, n) => "/" + parts.slice(0, n + 1).join("/"));
}

function makeDirectory(nodes, directory, isDirectory) {
  if (nodes.has(directory) && !isDirectory(directory)) refuse("ENOTDIR", directory);
  nodes.set(directory, null);
}

/** Pyodide, its file system `fs`: what the worker asks of it is kept in `asked`. */
function python(fs, asked) {
  return {
    FS: fs,
    loadPackage: async (names) => asked.packages.push(...names),
    pyimport: (name) => {
      asked.imported.push(name);
      return { install: async (requirements) => asked.installed.push(...requirements) };
    },
    runPython: (code) => {
      asked.code.push(code);
      const listed = [...fs.nodes.keys()].filter((key) => fs.nodes.get(key) !== null).sort();
      return { toJs: () => [listed.length ? 1 : 0, listed.join(" ")] };
    },
  };
}

/** The worker's global scope: Pyodide's loader (failing with `fails`), the wheel's name, github.js's reader. */
function workerScope(pyodide, asked, posted, { fails, readRepository }) {
  return vm.createContext({
    postMessage: (message) => posted.push(structuredClone(message)), // as a worker posts it
    importScripts: (...urls) => {
      assert.deepEqual(urls, ["https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.js", "github.js"]);
    },
    loadPyodide: async (options) => {
      asked.loads += 1;
      asked.indexURL = options.indexURL;
      if (fails) throw new Error(fails);
      return pyodide;
    },
    fetch: async (url) => ({
      text: async () => (url === "wheel.txt" ? " project_validator-1.0-py3-none-any.whl\n" : ""),
    }),
    URL,
    JSON,
    Uint8Array,
    readRepository,
    self: { location: { href: "https://example.com/app/worker.js" } },
  });
}

/** The worker in a context of its own: what it posts, what it asks of Pyodide, and how to send it a message. */
function worker({ fails = null, readRepository = null } = {}) {
  const posted = [];
  const fs = fileSystem();
  const asked = { loads: 0, packages: [], imported: [], installed: [], code: [] };
  const context = workerScope(python(fs, asked), asked, posted, { fails, readRepository });
  run(context, "web/worker.js");
  const send = async (data) => {
    await context.self.onmessage({ data });
    await settled();
  };
  return { posted, fs, asked, send };
}

const FOLDER = {
  root: "shop",
  files: [
    { path: "shop/main.py", size: 3, bytes: new TextEncoder().encode("1\n\n").buffer },
    { path: "shop/data/big.bin", size: 7, bytes: null },
  ],
};

test("a folder is written into Pyodide's file system and validated", async () => {
  const { posted, fs, asked, send } = worker();
  await send(FOLDER);
  assert.equal(asked.indexURL, "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/");
  assert.deepEqual(asked.packages, ["pyyaml", "micropip"]);
  assert.deepEqual(asked.imported, ["micropip"]);
  assert.deepEqual(asked.installed, ["https://example.com/app/project_validator-1.0-py3-none-any.whl", "pathspec"]);
  assert.equal(asked.code[0], 'from project_validator.web import report\nreport("/project/shop")');
  assert.deepEqual([...fs.nodes.get("/project/shop/main.py")], [49, 10, 10]);
  assert.equal(fs.nodes.get("/project/shop/data/big.bin").length, 7); // its size alone
  assert.deepEqual(
    posted.map((message) => [message.kind, message.text]),
    [
      ["progress", "Loading Python (about 13 MB, cached after the first time)"],
      ["progress", "Installing the validator"],
      ["progress", "Copying 2 files"],
      ["progress", "Validating"],
      ["report", undefined],
    ],
  );
  assert.deepEqual(posted.at(-1), {
    kind: "report",
    code: 1,
    html: "/project/shop/data/big.bin /project/shop/main.py",
    commit: null,
  });
});

test("a run replaces the project of the run before, and Pyodide loads once", async () => {
  const { posted, fs, asked, send } = worker();
  await send(FOLDER);
  await send({ root: "other", files: [{ path: "other/a.py", size: 1, bytes: new Uint8Array([49]).buffer }] });
  assert.equal(asked.loads, 1);
  assert.equal(posted.at(-1).html, "/project/other/a.py");
  assert.deepEqual([...fs.nodes.keys()].sort(), ["/", "/project", "/project/other", "/project/other/a.py"]);
});

test("a repository is read with github.js, and the report names its commit", async () => {
  const reads = [];
  const readRepository = async (repository, token, progress) => {
    reads.push([repository, token]);
    progress("Fetched 1 of 1 files");
    return { root: "r", commit: "c0ffee", files: [{ path: "r/a.py", size: 1, bytes: new Uint8Array([49]).buffer }] };
  };
  const { posted, send } = worker({ readRepository });
  await send({ repository: { owner: "o", name: "r", ref: "main" }, token: "t" });
  assert.deepEqual(reads, [[{ owner: "o", name: "r", ref: "main" }, "t"]]);
  const progress = posted.filter((message) => message.kind === "progress").map((message) => message.text);
  assert.deepEqual(progress.slice(0, 2), [
    "Loading Python (about 13 MB, cached after the first time)",
    "Reading o/r@main",
  ]);
  assert.ok(progress.includes("Fetched 1 of 1 files"));
  assert.ok(progress.includes("Copying 1 files"));
  assert.deepEqual(posted.at(-1), { kind: "report", code: 1, html: "/project/r/a.py", commit: "c0ffee" });
});

test("an empty project reports what the validator says of it", async () => {
  const { posted, send } = worker();
  await send({ root: "empty", files: [] });
  assert.deepEqual(posted.at(-1), { kind: "report", code: 0, html: "", commit: null });
});

test("a failure says what failed", async () => {
  const { posted, send } = worker({ fails: "no network" });
  await send(FOLDER);
  assert.deepEqual(posted.at(-1), { kind: "failed", text: "Error: no network" });
});
