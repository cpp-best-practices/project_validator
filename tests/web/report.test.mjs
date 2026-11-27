// The HTML report's scripts (project_validator/views/assets: report.js and theme.js) in jsdom, on a report the Python
// package of this checkout writes.
import assert from "node:assert/strict";
import { before, test } from "node:test";
import { page, report, run } from "./load.mjs";

let html = "";
before(() => {
  html = report();
});

/** Facts to browse: `count` of them, of two kinds, every third with a link, and fields of each sort. */
function facts(count) {
  const listed = Array.from({ length: count }, (_, n) => ({
    k: n % 2 ? "SourceFile" : "BuildFile",
    o: `src/f${n}.py`,
    u: n % 3 ? null : `https://example.com/f${n}`,
    f: { language: "Python", lines: n, tags: n % 4 ? ["a"] : [], empty: "", none: null, off: false, on: true },
  }));
  const kinds = [
    ["BuildFile", Math.ceil(count / 2), "A build file."],
    ["SourceFile", Math.floor(count / 2), ""],
  ];
  return JSON.stringify({ facts: listed, kinds });
}

/** The report at `hash`, its facts `data` if given, its scripts run (theme.js first, as the report runs them). */
function opened({ hash = "", data = null, storage = null } = {}) {
  const dom = page(html, `https://example.com/report.html${hash}`);
  const { window } = dom;
  if (data) window.document.getElementById("facts-data").textContent = data;
  if (storage) Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
  window.matchMedia = (query) => ({ matches: query === "(prefers-color-scheme: dark)" && window.prefersDark === true });
  run(dom.getInternalVMContext(), "project_validator/views/assets/theme.js");
  run(dom.getInternalVMContext(), "project_validator/views/assets/report.js");
  const document = window.document;
  return {
    window,
    document,
    $: (selector) => document.querySelector(selector),
    $$: (selector) => [...document.querySelectorAll(selector)],
  };
}

const shown = (node) => node.style.display !== "none";
const click = (node) => node.dispatchEvent(new node.ownerDocument.defaultView.MouseEvent("click", { bubbles: true }));

test("the results filter by status", () => {
  const { $, $$ } = opened();
  const skipped = $$('details.check[data-status="SKIP"]');
  const failed = $$('details.check[data-status="FAIL"]');
  assert.ok(skipped.length && failed.length);
  assert.ok(skipped.every((node) => !shown(node))); // SKIP starts hidden
  assert.ok(failed.every(shown));
  const button = $('.filter[data-filter="FAIL"]');
  click(button);
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.ok(failed.every((node) => !shown(node)));
  click(button);
  assert.ok(failed.every(shown));
});

test("the results filter by text, and a category with none shown is hidden", () => {
  const { window, $, $$ } = opened();
  const search = $("#result-search");
  search.value = "FUZZ-TESTING";
  search.dispatchEvent(new window.Event("input"));
  const visible = $$("details.check").filter(shown);
  assert.deepEqual(
    visible.map((node) => node.id),
    ["check-fuzz-testing"],
  );
  const categories = $$(".category");
  assert.equal(categories.filter(shown).length, 1);
  assert.ok(categories.filter(shown)[0].contains(visible[0]));
  assert.equal(categories.filter(shown)[0].style.display, "");
  search.value = "";
  search.dispatchEvent(new window.Event("input"));
  // The categories the search hid, that hold a result shown again, are shown again.
  const again = categories.filter(
    (category) => !category.contains(visible[0]) && [...category.querySelectorAll("details.check")].some(shown),
  );
  assert.ok(again.length);
  assert.deepEqual(
    again.map((category) => category.style.display),
    again.map(() => ""),
  );
});

test("a link to a result opens it, shown even where a filter hides it", () => {
  const { window, $ } = opened({ hash: "#check-license" });
  assert.equal($("#check-license").open, true);
  const skipped = $('details.check[data-status="SKIP"]');
  window.location.hash = "#" + skipped.id;
  window.dispatchEvent(new window.HashChangeEvent("hashchange"));
  assert.equal(skipped.open, true);
  assert.equal(skipped.style.display, "");
  window.location.hash = "#results"; // a section, not a result
  window.dispatchEvent(new window.HashChangeEvent("hashchange"));
  assert.equal($("#results").open, undefined);
});

test("the navigation follows the section on screen", () => {
  const { window, document, $$ } = opened();
  const links = $$(".topbar nav a");
  assert.ok(links.at(-1).classList.contains("active")); // jsdom lays nothing out: every section is at the top
  // On screen: a section whose top is above 120 pixels; the last of those is the one read.
  const tops = Object.fromEntries(links.map((link, n) => [link.getAttribute("href"), n < 2 ? 119 : 120]));
  for (const link of links) {
    const section = document.querySelector(link.getAttribute("href"));
    if (section) section.getBoundingClientRect = () => ({ top: tops[link.getAttribute("href")] });
  }
  document.dispatchEvent(new window.Event("scroll"));
  assert.deepEqual(
    links.map((link) => link.classList.contains("active")),
    links.map((_, n) => n === 1),
  );
});

test("the facts' kinds are buttons, with their count and what each is", () => {
  const { $$ } = opened({ data: facts(120) });
  const kinds = $$("#fact-kinds button");
  assert.deepEqual(
    kinds.map((button) => button.textContent),
    ["All facts120", "BuildFile60", "SourceFile60"],
  );
  assert.equal(kinds[1].title, "A build file.");
  assert.equal(kinds[2].hasAttribute("title"), false);
  assert.equal(kinds[0].hasAttribute("title"), false);
  assert.deepEqual(
    kinds.map((button) => button.className),
    ["active", "", ""],
  );
  assert.deepEqual(
    [...kinds[1].children].map((span) => [span.getAttribute("class"), span.textContent]),
    [
      [null, "BuildFile"],
      ["n", "60"],
    ],
  );
});

test("the facts are shown a page at a time", () => {
  const { $ } = opened({ data: facts(120) });
  assert.equal($("#fact-doc").textContent, "Every fact, in the order the stages found them.");
  assert.equal($("#fact-page").textContent, "1 to 50 of 120");
  assert.equal($("#fact-list").children.length, 50);
  assert.equal($("#fact-list").childNodes.length, 50); // the facts alone
  assert.equal($("#fact-prev").disabled, true);
  assert.equal($("#fact-next").disabled, false);
  click($("#fact-next"));
  click($("#fact-next"));
  assert.equal($("#fact-page").textContent, "101 to 120 of 120");
  assert.equal($("#fact-next").disabled, true);
  click($("#fact-prev"));
  assert.equal($("#fact-page").textContent, "51 to 100 of 120");
  assert.equal($("#fact-prev").disabled, false);
});

test("the facts are browsed by kind, and searched", () => {
  const { window, $, $$ } = opened({ data: facts(120) });
  const kinds = $$("#fact-kinds button");
  click($("#fact-next"));
  click(kinds[2]);
  assert.ok(kinds[2].classList.contains("active") && !kinds[0].classList.contains("active"));
  assert.equal($("#fact-doc").textContent, "");
  assert.equal($("#fact-page").textContent, "1 to 50 of 60"); // from the first page again
  click(kinds[1]);
  assert.equal($("#fact-doc").textContent, "A build file.");
  const search = $("#fact-search");
  search.value = "F99.PY";
  search.dispatchEvent(new window.Event("input"));
  assert.equal($("#fact-page").textContent, "No fact matches.");
  click(kinds[0]);
  assert.equal($("#fact-page").textContent, "1 to 1 of 1");
  for (const text of ["buildfile src/f2.py", 'src/f2.py {"language"']) {
    search.value = text; // the kind, the origin and the fields, as one text
    search.dispatchEvent(new window.Event("input"));
    assert.equal($("#fact-page").textContent, "1 to 1 of 1");
  }
});

test("a fact shows its kind, its origin (a link where it has one) and the fields that say something", () => {
  const { $$ } = opened({ data: facts(4) });
  const [linked, plain] = $$("#fact-list .fact");
  assert.equal(linked.querySelector("strong").textContent, "BuildFile");
  assert.equal(linked.firstChild.textContent, "BuildFile src/f0.py");
  const unclassed = [...linked.querySelectorAll("strong, dl, dt, dd"), linked.firstChild];
  assert.ok(unclassed.every((node) => !node.hasAttribute("class")));
  const origin = linked.querySelector("a.origin");
  assert.equal(origin.href, "https://example.com/f0");
  assert.equal(origin.target, "_blank");
  assert.equal(origin.rel, "noopener");
  assert.equal(plain.querySelector("span.origin.muted").textContent, "src/f1.py");
  const fields = (fact) => [...fact.querySelectorAll("dt")].map((dt) => [dt.textContent, dt.nextSibling.textContent]);
  assert.deepEqual(fields(linked), [
    ["language", "Python"],
    ["lines", "0"],
    ["on", "true"],
  ]);
  assert.deepEqual(fields(plain), [
    ["language", "Python"],
    ["lines", "1"],
    ["tags", '["a"]'],
    ["on", "true"],
  ]);
});

test("trees open and close with the arrow keys", () => {
  const { window, document } = opened({ data: facts(1) });
  document.body.insertAdjacentHTML(
    "beforeend",
    '<details id="outer" open><summary id="o">o</summary><div><details id="inner"><summary id="i">i</summary></details></div></details>',
  );
  const key = (id, name) => {
    const event = new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true });
    document.getElementById(id).dispatchEvent(event);
    return event.defaultPrevented;
  };
  const inner = document.getElementById("inner");
  assert.equal(key("i", "ArrowRight"), true);
  assert.equal(inner.open, true);
  assert.equal(key("i", "ArrowRight"), false); // already open
  assert.equal(key("i", "ArrowLeft"), true);
  assert.equal(inner.open, false);
  key("i", "ArrowLeft"); // closed: on to the summary around it
  assert.equal(document.activeElement.id, "o");
  key("o", "ArrowLeft");
  assert.equal(document.getElementById("outer").open, false);
  assert.equal(key("o", "ArrowLeft"), true); // closed, and nothing around it
  assert.equal(key("outer", "ArrowRight"), false); // not a summary
  assert.equal(key("o", "Enter"), false);
});

/** A localStorage that keeps `saved` and the theme set, or one that refuses to be used. */
function storage(saved, refuses = false) {
  const kept = new Map([["pv-theme", saved]]);
  const refused = () => {
    if (refuses) throw new Error("denied");
  };
  return {
    kept,
    getItem: (key) => (refused(), kept.get(key) ?? null),
    setItem: (key, value) => (refused(), kept.set(key, value)),
  };
}

test("the theme kept is the one shown, and the button switches it and keeps it", () => {
  const kept = storage("dark");
  const { document, $ } = opened({ storage: kept });
  assert.equal(document.documentElement.dataset.theme, "dark");
  click($(".theme-toggle"));
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.equal(kept.kept.get("pv-theme"), "light");
  click($(".theme-toggle"));
  assert.equal(document.documentElement.dataset.theme, "dark");
});

test("with no theme kept, the button switches from the system's", () => {
  for (const dark of [true, false]) {
    const { window, document, $ } = opened({ storage: storage(null) });
    window.prefersDark = dark;
    assert.equal(document.documentElement.dataset.theme, undefined);
    click($(".theme-toggle"));
    assert.equal(document.documentElement.dataset.theme, dark ? "light" : "dark");
  }
});

test("a storage that refuses is no matter, and a click elsewhere changes nothing", () => {
  const { document, $ } = opened({ storage: storage(null, true) });
  click($(".theme-toggle"));
  assert.equal(document.documentElement.dataset.theme, "dark");
  click(document.body);
  assert.equal(document.documentElement.dataset.theme, "dark");
  document.dispatchEvent(new document.defaultView.MouseEvent("click")); // a target with no closest()
  assert.equal(document.documentElement.dataset.theme, "dark");
});
