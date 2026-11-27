// The validator, in a Web Worker so that a long run never freezes the page (upstream #127): Python under Pyodide,
// the validator's wheel installed beside this file, the picked folder's files written into Pyodide's file system,
// and the HTML report sent back. Messages: in, {files: [{path, bytes}]} (bytes an ArrayBuffer, or a size alone for a
// file too large to read, which only large-files asks about); out, {kind: "progress"|"report"|"failed", ...}.
"use strict";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/";
importScripts(PYODIDE + "pyodide.js");

let ready = null;

async function start() {
  postMessage({ kind: "progress", text: "Loading Python (about 13 MB, cached after the first time)" });
  const pyodide = await loadPyodide({ indexURL: PYODIDE });
  await pyodide.loadPackage(["pyyaml", "micropip"]);
  postMessage({ kind: "progress", text: "Installing the validator" });
  const wheel = (await (await fetch("wheel.txt")).text()).trim();
  const micropip = pyodide.pyimport("micropip");
  await micropip.install([new URL(wheel, self.location.href).href, "pathspec"]);
  return pyodide;
}

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

self.onmessage = async (event) => {
  try {
    ready = ready || start();
    const pyodide = await ready;
    postMessage({ kind: "progress", text: `Copying ${event.data.files.length} files` });
    write(pyodide, event.data.files);
    postMessage({ kind: "progress", text: "Validating" });
    const root = "/project/" + event.data.root;
    const [code, html] = pyodide.runPython(
      `from project_validator.web import report\nreport(${JSON.stringify(root)})`
    ).toJs();
    postMessage({ kind: "report", code, html });
  } catch (error) {
    postMessage({ kind: "failed", text: String(error) });
  }
};
