// The validator, in a Web Worker so that a long run never freezes the page (upstream #127): Python under Pyodide,
// the validator's wheel installed beside this file, the project's files written into Pyodide's file system, and the
// HTML report sent back. Messages in: {root, files: [{path, size, bytes}]}, a picked folder's (bytes an ArrayBuffer,
// or null for a file too large to read, which only large-files asks about), or {repository, token}, a GitHub
// repository to read (see github.js). Out: {kind: "progress"|"report"|"failed", ...}.
"use strict";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/";
importScripts(PYODIDE + "pyodide.js", "github.js");

/**
 * What the worker uses of Pyodide (https://pyodide.org/en/stable/usage/api/js-api.html).
 * @typedef {{
 *   mkdirTree(path: string): void, writeFile(path: string, bytes: Uint8Array): void,
 *   truncate(path: string, size: number): void, analyzePath(path: string): { exists: boolean },
 *   readdir(path: string): string[], stat(path: string): { mode: number }, isDir(mode: number): boolean,
 *   rmdir(path: string): void, unlink(path: string): void,
 * }} FileSystem
 * @typedef {{
 *   FS: FileSystem, loadPackage(names: string[]): Promise<void>,
 *   pyimport(name: string): { install(requirements: string[]): Promise<void> },
 *   runPython(code: string): { toJs(): [number, string] },
 * }} Pyodide
 */

/** pyodide.js's loader, a global of the worker once imported. */
/** @type {(options: { indexURL: string }) => Promise<Pyodide>} */
const loadPython = /** @type {any} */ (globalThis).loadPyodide;

/** @type {Promise<Pyodide> | null} */
let ready = null;

async function start() {
  postMessage({ kind: "progress", text: "Loading Python (about 13 MB, cached after the first time)" });
  const pyodide = await loadPython({ indexURL: PYODIDE });
  await pyodide.loadPackage(["pyyaml", "micropip"]);
  postMessage({ kind: "progress", text: "Installing the validator" });
  const wheel = await (await fetch("wheel.txt")).text(); // a URL ignores the spaces around it
  const micropip = pyodide.pyimport("micropip");
  await micropip.install([new URL(wheel, self.location.href).href, "pathspec"]);
  return pyodide;
}

/**
 * @param {Pyodide} pyodide
 * @param {ProjectFile[]} files
 */
function write(pyodide, files) {
  const fs = pyodide.FS;
  for (const file of files) {
    const path = "/project/" + file.path;
    fs.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    if (file.bytes) {
      fs.writeFile(path, new Uint8Array(file.bytes));
    } else {
      fs.writeFile(path, new Uint8Array(0));
      fs.truncate(path, file.size); // its size, for large-files; nothing reads it
    }
  }
}

// A run replaces the project of the run before.
/** @param {Pyodide} pyodide */
function removeProject(pyodide) {
  const fs = pyodide.FS;
  /** @param {string} path */
  const remove = (path) => {
    for (const name of fs.readdir(path)) {
      if (name === "." || name === "..") continue;
      const child = path + "/" + name;
      if (fs.isDir(fs.stat(child).mode)) {
        remove(child);
        fs.rmdir(child);
      } else {
        fs.unlink(child);
      }
    }
  };
  if (fs.analyzePath("/project").exists) remove("/project");
}

self.onmessage = async (event) => {
  try {
    ready = ready || start();
    let { root, files, repository, token } = event.data;
    let commit = null;
    if (repository) {
      const { owner, name, ref } = repository;
      postMessage({ kind: "progress", text: `Reading ${owner}/${name}@${ref}` });
      const progress = (/** @type {string} */ text) => postMessage({ kind: "progress", text });
      ({ root, files, commit } = await readRepository(repository, token, progress));
    }
    const pyodide = await ready;
    postMessage({ kind: "progress", text: `Copying ${files.length} files` });
    removeProject(pyodide);
    write(pyodide, files);
    postMessage({ kind: "progress", text: "Validating" });
    root = "/project/" + root;
    const [code, html] = pyodide
      .runPython(`from project_validator.web import report\nreport(${JSON.stringify(root)})`)
      .toJs();
    postMessage({ kind: "report", code, html, commit });
  } catch (error) {
    postMessage({ kind: "failed", text: String(error) });
  }
};
