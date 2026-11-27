// The page (upstream #127): pick a folder, watch the progress, read the report. The folder never leaves the browser.
"use strict";

// Files larger than this are not read: their size alone is given, as large-files asks for nothing else.
const MOST_BYTES = 5 * 1024 * 1024;
// What a checkout holds that is no part of the project.
const SKIPPED = /(^|\/)(\.git|node_modules|\.venv|__pycache__)(\/|$)/;

const picker = document.getElementById("folder");
const form = document.getElementById("github");
const repositoryInput = document.getElementById("repository");
const tokenInput = document.getElementById("token");
const status = document.getElementById("status");
const frame = document.getElementById("report");
const download = document.getElementById("download");
const worker = new Worker("worker.js");

worker.onmessage = (event) => {
  const message = event.data;
  switch (message.kind) {
    case "progress":
      status.textContent = message.text + "…";
      break;
    case "report":
      status.textContent =
        (message.code === 0 ? "Done: every check passed." : "Done: some checks did not pass.") +
        (message.commit ? ` (commit ${message.commit.slice(0, 12)})` : "");
      frame.srcdoc = message.html;
      frame.hidden = false;
      download.href = URL.createObjectURL(new Blob([message.html], { type: "text/html" }));
      download.hidden = false;
      picker.disabled = form.elements.go.disabled = false;
      break;
    case "failed":
      status.textContent = "The validator could not run: " + message.text;
      picker.disabled = form.elements.go.disabled = false;
      break;
  }
};

picker.addEventListener("change", async () => {
  const chosen = Array.from(picker.files).filter((file) => !SKIPPED.test(file.webkitRelativePath));
  if (!chosen.length) return;
  picker.disabled = true;
  frame.hidden = download.hidden = true;
  status.textContent = `Reading ${chosen.length} files…`;
  const root = chosen[0].webkitRelativePath.split("/")[0];
  const files = await Promise.all(
    chosen.map(async (file) => ({
      path: file.webkitRelativePath,
      size: file.size,
      bytes: file.size <= MOST_BYTES ? await file.arrayBuffer() : null,
    }))
  );
  const buffers = files.filter((file) => file.bytes).map((file) => file.bytes);
  worker.postMessage({ root, files }, buffers);
});

// A GitHub repository, by owner/name@ref: the page's address keeps it (?repo=...), so a run can be linked to.
function runRepository(text) {
  const repository = parseRepository(text);
  if (!repository) {
    status.textContent = "Write the repository as owner/name, or owner/name@ref.";
    return;
  }
  picker.disabled = form.elements.go.disabled = true;
  frame.hidden = download.hidden = true;
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
