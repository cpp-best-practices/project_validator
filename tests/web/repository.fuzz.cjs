// Fuzzing what the page makes of a visitor's input (Jazzer.js: `npm run fuzz`): parseRepository never throws, and what
// it accepts reads back the same once written out; encodePath encodes every part of a path, which decodes back whole.
"use strict";
const assert = require("node:assert/strict");
const { mkdtempSync, readFileSync, writeFileSync } = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// github.js is a page's script, whose functions are globals: required as a module with them exported, Jazzer.js
// instruments it, and the fuzzer follows its branches.
const source = readFileSync(path.join(__dirname, "..", "..", "web", "github.js"), "utf8");
const module_ = path.join(mkdtempSync(path.join(os.tmpdir(), "fuzz-")), "github.cjs");
writeFileSync(module_, source + "\nmodule.exports = { parseRepository, encodePath };\n");
const github = require(module_);

module.exports.fuzz = function (data) {
  const text = data.toString("utf8");
  const parsed = github.parseRepository(text);
  if (parsed) {
    assert.match(parsed.owner, /^[\w.-]+$/);
    assert.match(parsed.name, /^[\w.-]+$/);
    assert.match(parsed.ref, /^\S+$/);
    const again = github.parseRepository(`${parsed.owner}/${parsed.name}@${parsed.ref}`);
    assert.deepEqual({ ...again }, { ...parsed });
  }
  const encoded = github.encodePath(text);
  assert.equal(encoded.split("/").length, text.split("/").length);
  assert.equal(encoded.split("/").map(decodeURIComponent).join("/"), text);
};
