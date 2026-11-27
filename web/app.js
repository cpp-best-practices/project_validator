// The page (upstream #127): pick a folder, watch the progress, read the report. The folder never leaves the browser.
"use strict";

// Files larger than this are not read: their size alone is given, as large-files asks for nothing else.
const MOST_BYTES = 5 * 1024 * 1024;
// What a checkout holds that is no part of the project.
const SKIPPED = /(^|\/)(\.git|node_modules|\.venv|__pycache__)(\/|$)/;

/**
 * The page's element of `id`, as the type it is in index.html.
 * @template {HTMLElement} T
 * @param {string} id
 * @param {new () => T} type
 * @returns {T}
 */
function byId(id, type) {
  const found = document.getElementById(id);
  if (!(found instanceof type)) throw new Error(`index.html has no ${type.name} #${id}`);
  return found;
}

const picker = byId("folder", HTMLInputElement);
const form = byId("github", HTMLFormElement);
const go = byId("go", HTMLButtonElement);
const repositoryInput = byId("repository", HTMLInputElement);
const tokenInput = byId("token", HTMLInputElement);
const statusLine = byId("status", HTMLElement);
const frame = byId("report", HTMLIFrameElement);
const download = byId("download", HTMLAnchorElement);
const worker = new Worker("worker.js");

/** @param {boolean} busy */
function setBusy(busy) {
  picker.disabled = go.disabled = busy;
  if (busy) frame.hidden = download.hidden = true;
}

worker.onmessage = (event) => {
  const message = event.data;
  switch (message.kind) {
    case "progress":
      statusLine.textContent = message.text + "…";
      break;
    case "report":
      statusLine.textContent =
        (message.code === 0 ? "Done: every check passed." : "Done: some checks did not pass.") +
        (message.commit ? ` (commit ${message.commit.slice(0, 12)})` : "");
      frame.srcdoc = message.html;
      frame.hidden = false;
      download.href = URL.createObjectURL(new Blob([message.html], { type: "text/html" }));
      download.hidden = false;
      setBusy(false);
      break;
    case "failed":
      statusLine.textContent = "The validator could not run: " + message.text;
      setBusy(false);
      break;
  }
};

picker.addEventListener("change", async () => {
  const chosen = Array.from(/** @type {FileList} */ (picker.files)).filter(
    (file) => !SKIPPED.test(file.webkitRelativePath),
  );
  if (!chosen.length) return;
  setBusy(true);
  statusLine.textContent = `Reading ${chosen.length} files…`;
  const root = chosen[0].webkitRelativePath.split("/")[0];
  const files = await Promise.all(
    chosen.map(async (file) => ({
      path: file.webkitRelativePath,
      size: file.size,
      bytes: file.size <= MOST_BYTES ? await file.arrayBuffer() : null,
    })),
  );
  const buffers = files.flatMap((file) => (file.bytes ? [file.bytes] : []));
  worker.postMessage({ root, files }, buffers);
});

// A GitHub repository, by owner/name@ref: the page's address keeps it (?repo=...), so a run can be linked to.
/** @param {string} text */
function runRepository(text) {
  const repository = parseRepository(text);
  if (!repository) {
    statusLine.textContent = "Write the repository as owner/name, or owner/name@ref.";
    return;
  }
  setBusy(true);
  history.replaceState(null, "", "?repo=" + encodeURIComponent(text.trim()));
  worker.postMessage({ repository, token: tokenInput.value.trim() || null });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runRepository(repositoryInput.value);
});

const linked = new URLSearchParams(location.search).get("repo");
if (linked) {
  repositoryInput.value = linked;
  runRepository(linked);
}
