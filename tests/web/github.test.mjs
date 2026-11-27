// The page reads a repository through GitHub's API and raw.githubusercontent.com (web/github.js), GitHub's answers
// stubbed.
import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";
import { run } from "./load.mjs";

const TREE = [
  { path: "README.md", type: "blob", mode: "100644", size: 6 },
  { path: "src/a b.py", type: "blob", mode: "100644", size: 4 },
  { path: "big.bin", type: "blob", mode: "100644", size: 2000000 },
  { path: "edge.bin", type: "blob", mode: "100644", size: 1024 * 1024 }, // the largest fetched
  { path: "link", type: "blob", mode: "120000", size: 4 },
  { path: "src", type: "tree", mode: "040000" },
];

function ok(body) {
  return { ok: true, status: 200, json: async () => body, arrayBuffer: async () => Buffer.from(String(body)) };
}

/**
 * github.js in a context of its own, with `fetch` answering as `answer` does: every URL asked and its headers kept,
 * the most fetches in flight at once, and the waits before each retry (made at once).
 */
function github(answer) {
  const asked = [];
  const headers = [];
  const waits = [];
  const flight = { now: 0, most: 0 };
  const context = vm.createContext({
    fetch: async (url, options) => {
      asked.push(url);
      if (options) headers.push({ ...options.headers });
      flight.most = Math.max(flight.most, ++flight.now);
      await new Promise((resolve) => setTimeout(resolve, 0));
      flight.now -= 1;
      return answer(url, options);
    },
    setTimeout: (callback, wait) => {
      waits.push(wait);
      setTimeout(callback, 0);
    },
  });
  run(context, "web/github.js"); // its functions are the context's globals, as they are the page's
  const { parseRepository, encodePath, readRepository } = context;
  return { parseRepository, encodePath, readRepository, asked, headers, waits, flight };
}

/** GitHub as the tests expect it: the commit only with the token `t`, README.md failing once, `a b.py` not on raw. */
function stubbed() {
  let flaky = 1;
  return github((url, options) => {
    const token = options?.headers.Authorization === "Bearer t";
    if (url.includes("/commits/")) return token ? ok({ sha: "c0ffee" }) : { ok: false, status: 403 };
    if (url.includes("/git/trees/")) return ok({ tree: TREE, truncated: false });
    const raw = url.includes("raw.githubusercontent.com");
    if (raw && url.endsWith("README.md") && flaky-- > 0) return { ok: false, status: 501 };
    if (raw && url.includes("a%20b.py")) return { ok: false, status: 404 };
    return ok(url.includes("README") ? "readme" : "code");
  });
}

test("a repository is written owner/name and a ref", () => {
  const { parseRepository } = stubbed();
  const written = ["owner/repo", "o/r@v1.2", " o/r.git@feature/x ", "o/my.github.io"];
  const refused = ["nope", "", undefined, "a b/c", "o/r x", "o/r@a b", "o/r@ b", "o/r@", "o/r/s"];
  const parsed = [...written, ...refused].map(parseRepository);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), [
    { owner: "owner", name: "repo", ref: "HEAD" },
    { owner: "o", name: "r", ref: "v1.2" },
    { owner: "o", name: "r", ref: "feature/x" },
    { owner: "o", name: "my.github.io", ref: "HEAD" },
    ...refused.map(() => null),
  ]);
});

test("each part of a path is encoded, not the slashes", () => {
  assert.equal(stubbed().encodePath("src/a b/#c.py"), "src/a%20b/%23c.py");
});

test("every file of the commit is read but links and large ones", async () => {
  const reader = stubbed();
  const progress = [];
  const read = await reader.readRepository(reader.parseRepository("o/r@main"), "t", (text) => progress.push(text));
  assert.equal(read.root, "r");
  assert.equal(read.commit, "c0ffee");
  assert.equal(read.truncated, false);
  const files = Array.from(read.files, (file) => [
    file.path,
    file.size,
    file.bytes && Buffer.from(file.bytes).toString(),
  ]);
  assert.deepEqual(files, [
    ["r/README.md", 6, "readme"],
    ["r/src/a b.py", 4, "code"],
    ["r/big.bin", 2000000, null],
    ["r/edge.bin", 1024 * 1024, "code"],
  ]);
  assert.deepEqual(progress, ["Fetched 4 of 4 files"]);
  assert.ok(reader.asked.includes("https://api.github.com/repos/o/r/commits/main"));
  assert.ok(reader.asked.includes("https://api.github.com/repos/o/r/git/trees/c0ffee?recursive=1"));
});

test("the API is asked for its JSON, with the token when one is given", async () => {
  const reader = stubbed();
  await reader.readRepository(reader.parseRepository("o/r"), "t", () => {});
  const api = { Accept: "application/vnd.github+json" };
  assert.deepEqual(reader.headers, [
    { ...api, Authorization: "Bearer t" },
    { ...api, Authorization: "Bearer t" },
  ]);
  const anonymous = github((url) => (url.includes("/commits/") ? ok({ sha: "s" }) : ok({ tree: [] })));
  await anonymous.readRepository(anonymous.parseRepository("o/r"), null, () => {});
  assert.deepEqual(anonymous.headers, [api, api]);
});

test("a failed fetch is tried again, a little later each time, then read from jsDelivr", async () => {
  const reader = stubbed();
  await reader.readRepository(reader.parseRepository("o/r"), "t", () => {});
  assert.deepEqual(reader.waits.toSorted(), [250, 250, 500, 750]); // README.md once, a b.py three times
  const readme = reader.asked.filter((url) => url.endsWith("README.md"));
  assert.deepEqual(readme, Array(2).fill("https://raw.githubusercontent.com/o/r/c0ffee/README.md"));
  const tries = reader.asked.filter((url) => url.endsWith("a%20b.py"));
  assert.deepEqual(tries, [
    ...Array(3).fill("https://raw.githubusercontent.com/o/r/c0ffee/src/a%20b.py"),
    "https://cdn.jsdelivr.net/gh/o/r@c0ffee/src/a%20b.py",
  ]);
});

test("a file no host serves fails the read", async () => {
  const reader = github((url) => {
    if (url.includes("/commits/")) return ok({ sha: "c0ffee" });
    if (url.includes("/git/trees/")) return ok({ tree: TREE.slice(0, 1) });
    throw new TypeError("network down");
  });
  await assert.rejects(
    reader.readRepository(reader.parseRepository("o/r"), null, () => {}),
    /could not fetch https:\/\/raw\.githubusercontent\.com\/o\/r\/c0ffee\/README\.md/,
  );
});

test("the API's answers say why a read failed", async () => {
  const limited = stubbed();
  await assert.rejects(
    limited.readRepository(limited.parseRepository("o/r"), null, () => {}),
    /limit is reached/,
  );
  for (const status of [429, 404]) {
    const reader = github(() => ({ ok: false, status }));
    const expected = status === 429 ? /limit is reached/ : /GitHub answered 404 for repos\/o\/r\/commits\/HEAD/;
    await assert.rejects(
      reader.readRepository(reader.parseRepository("o/r"), null, () => {}),
      expected,
    );
  }
});

test("progress is told every fifty files, and once at the end", async () => {
  const tree = Array.from({ length: 120 }, (_, n) => ({ path: `f${n}`, type: "blob", mode: "100644", size: 1 }));
  const reader = github((url) => (url.includes("/commits/") ? ok({ sha: "s" }) : ok({ tree, truncated: true })));
  const progress = [];
  const read = await reader.readRepository(reader.parseRepository("o/r"), null, (text) => progress.push(text));
  assert.deepEqual(progress, ["Fetched 50 of 120 files", "Fetched 100 of 120 files", "Fetched 120 of 120 files"]);
  assert.equal(read.truncated, true);
  assert.equal(reader.flight.most, 32); // no more fetches at once than that
});

test("a repository with no files reads none", async () => {
  const reader = github((url) => (url.includes("/commits/") ? ok({ sha: "s" }) : ok({ tree: [] })));
  const read = await reader.readRepository(reader.parseRepository("o/r"), null, () => {});
  assert.deepEqual(Array.from(read.files), []);
});
