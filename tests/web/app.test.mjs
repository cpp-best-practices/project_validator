// The page (web/index.html and web/app.js) in jsdom: the worker stood in for by one that keeps what it is sent and
// answers as the tests say.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { ROOT, page, run, settled } from "./load.mjs";

const INDEX = readFileSync(path.join(ROOT, "web/index.html"), "utf8");
const INITIAL_STATUS = page(INDEX).window.document.getElementById("status").textContent;

/** The page at `url`, its scripts run: what it sends its worker, how the worker answers, and its elements. */
function app(url = "https://example.com/app/", html = INDEX) {
  const dom = page(html, url);
  const window = dom.window;
  const sent = [];
  let worker = null;
  window.Worker = class {
    constructor(script) {
      assert.equal(script, "worker.js");
      worker = this;
    }
    postMessage(message, transfer) {
      sent.push({ message: structuredClone(message), transfer }); // as a worker receives it
    }
  };
  const blobs = [];
  window.URL.createObjectURL = (blob) => {
    blobs.push(blob);
    return `blob:${blob.type}`;
  };
  const context = dom.getInternalVMContext();
  run(context, "web/github.js");
  run(context, "web/app.js");
  const document = window.document;
  const element = (id) => document.getElementById(id);
  const answer = (message) => worker.onmessage({ data: message });
  return { window, document, element, sent, answer, blobs };
}

/** A file as a folder picker gives it: its path below the folder picked, its size and its bytes. */
function picked(relative, size = 1) {
  return { webkitRelativePath: relative, size, arrayBuffer: async () => new ArrayBuffer(size) };
}

function pick({ window, element }, files) {
  const picker = element("folder");
  Object.defineProperty(picker, "files", { value: files, configurable: true });
  picker.dispatchEvent(new window.Event("change"));
}

test("a folder picked is read, but what no project holds and what is too large", async () => {
  const page = app();
  const most = 5 * 1024 * 1024;
  pick(page, [
    picked("shop/main.py", 3),
    picked("shop/.git/HEAD"),
    picked("shop/sub/.git"), // a submodule's
    picked("shop/web/node_modules/x/index.js"),
    picked("shop/edge.bin", most),
    picked("shop/big.bin", most + 1),
  ]);
  assert.equal(page.element("status").textContent, "Reading 3 files…");
  assert.equal(page.element("folder").disabled, true);
  await settled();
  const [{ message, transfer }] = page.sent;
  assert.equal(message.root, "shop");
  assert.deepEqual(
    message.files.map((file) => [file.path, file.size, file.bytes && file.bytes.byteLength]),
    [
      ["shop/main.py", 3, 3],
      ["shop/edge.bin", most, most],
      ["shop/big.bin", most + 1, null],
    ],
  );
  assert.equal(transfer.length, 2); // the bytes move to the worker, not copied
});

test("a folder with nothing to read sends nothing", async () => {
  const page = app();
  pick(page, [picked("node_modules/x/index.js"), picked(".venv/bin/python")]); // folders picked themselves
  await settled();
  assert.deepEqual(page.sent, []);
  assert.equal(page.element("folder").disabled, false);
});

test("the worker's progress, report and failure are shown", async () => {
  const page = app();
  assert.equal(page.element("status").textContent, INITIAL_STATUS);
  page.answer({ kind: "progress", text: "Validating" });
  assert.equal(page.element("status").textContent, "Validating…");
  page.answer({ kind: "report", code: 0, html: "<p>report</p>", commit: null });
  assert.equal(page.element("status").textContent, "Done: every check passed.");
  assert.equal(page.element("report").srcdoc, "<p>report</p>");
  assert.equal(page.element("report").hidden, false);
  assert.equal(page.element("download").href, "blob:text/html");
  assert.equal(page.element("download").hidden, false);
  assert.equal(await page.blobs[0].text(), "<p>report</p>");
  page.answer({ kind: "report", code: 1, html: "<p>again</p>", commit: "c0ffee0123456789" });
  assert.equal(page.element("status").textContent, "Done: some checks did not pass. (commit c0ffee012345)");
  page.answer({ kind: "failed", text: "Error: no network" });
  assert.equal(page.element("status").textContent, "The validator could not run: Error: no network");
  assert.equal(page.element("folder").disabled, false);
  page.answer({ kind: "unheard of" });
  assert.equal(page.element("status").textContent, "The validator could not run: Error: no network");
});

test("a new run hides the report of the last", () => {
  const page = app();
  page.answer({ kind: "report", code: 0, html: "<p>report</p>", commit: null });
  pick(page, [picked("shop/main.py")]);
  assert.equal(page.element("report").hidden, true);
  assert.equal(page.element("download").hidden, true);
});

test("a repository is read by owner/name@ref, and the address keeps it", () => {
  const page = app();
  page.element("repository").value = " o/r@v1 ";
  page.element("token").value = " t ";
  const submitted = new page.window.Event("submit", { cancelable: true });
  page.element("github").dispatchEvent(submitted);
  assert.equal(submitted.defaultPrevented, true); // the page stays
  assert.deepEqual(page.sent[0].message, { repository: { owner: "o", name: "r", ref: "v1" }, token: "t" });
  assert.equal(page.window.location.search, "?repo=o%2Fr%40v1");
  assert.equal(page.element("folder").disabled, true);
  page.element("token").value = "";
  page.element("github").requestSubmit();
  assert.equal(page.sent[1].message.token, null);
});

test("a repository written otherwise is asked for again", () => {
  const page = app();
  page.element("repository").value = "not a repository";
  page.element("github").requestSubmit();
  assert.deepEqual(page.sent, []);
  assert.equal(page.element("status").textContent, "Write the repository as owner/name, or owner/name@ref.");
});

test("a page that lacks an element the script needs says which", () => {
  const html = INDEX.replace('id="go"', 'id="gone"');
  assert.throws(() => app(undefined, html), /index\.html has no HTMLButtonElement #go/);
});

test("a link with ?repo= runs at once", () => {
  const page = app("https://example.com/app/?repo=o%2Fr");
  assert.equal(page.element("repository").value, "o/r");
  assert.deepEqual(page.sent[0].message.repository, { owner: "o", name: "r", ref: "HEAD" });
});
