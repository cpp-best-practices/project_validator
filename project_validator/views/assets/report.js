// The HTML report's behaviour: the navigation follows the section on screen, the results filter by status and text,
// a link to a result opens it, and the facts (JSON in #facts-data) are browsed by kind and searched.
"use strict";

/**
 * A fact as the report writes it: its kind, its origin, a link to the origin if it has one, and its fields.
 * @typedef {{ k: string, o: string, u: string | null, f: Record<string, unknown> }} Fact
 * @typedef {{ facts: Fact[], kinds: [string, number, string][] }} FactData
 */

/**
 * @param {string} tag
 * @param {string} [cls]
 * @param {string} [text]
 */
function element(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * The report's elements `selector` finds (each an HTML element).
 * @param {string} selector
 * @param {ParentNode} [root]
 * @returns {HTMLElement[]}
 */
function all(selector, root = document) {
  return /** @type {HTMLElement[]} */ (Array.from(root.querySelectorAll(selector)));
}

/**
 * The report's element of `id`, as the type it is.
 * @template {HTMLElement} T
 * @param {string} id
 * @returns {T}
 */
function byId(id) {
  return /** @type {T} */ (document.getElementById(id));
}

function followSections() {
  const links = all(".topbar nav a");
  const sections = links.map((a) => document.querySelector(/** @type {string} */ (a.getAttribute("href"))));
  function spy() {
    let current = 0;
    sections.forEach((s, i) => {
      if (s && s.getBoundingClientRect().top < 120) current = i;
    });
    links.forEach((a, i) => a.classList.toggle("active", i === current));
  }
  document.addEventListener("scroll", spy, { passive: true });
  spy();
}

/** @param {HTMLElement} node */
function visible(node) {
  return node.style.display !== "none";
}

/**
 * @param {Map<string, boolean>} shown
 * @param {HTMLInputElement} search
 */
function filterResults(shown, search) {
  const text = search.value.toLowerCase();
  all("details.check").forEach((d) => {
    const ok =
      shown.get(/** @type {string} */ (d.dataset.status)) !== false &&
      (!text || /** @type {string} */ (d.dataset.search).indexOf(text) >= 0);
    d.style.display = ok ? "" : "none";
  });
  all(".category").forEach((c) => {
    c.style.display = all("details.check", c).some(visible) ? "" : "none";
  });
}

function setUpFilters() {
  /** @type {Map<string, boolean>} */
  const shown = new Map();
  /** @type {HTMLInputElement} */
  const search = byId("result-search");
  const buttons = all(".filter");
  const filter = (/** @type {HTMLElement} */ b) => /** @type {string} */ (b.dataset.filter);
  buttons.forEach((b) => {
    shown.set(filter(b), b.getAttribute("aria-pressed") === "true");
  });
  buttons.forEach((b) => {
    b.addEventListener("click", () => {
      shown.set(filter(b), !shown.get(filter(b)));
      b.setAttribute("aria-pressed", String(shown.get(filter(b))));
      filterResults(shown, search);
    });
  });
  search.addEventListener("input", () => filterResults(shown, search));
  filterResults(shown, search);
}

function openLinkedResult() {
  const target = location.hash && document.getElementById(location.hash.slice(1));
  if (target instanceof HTMLDetailsElement) {
    target.open = true;
    target.style.display = "";
  }
}

class FactBrowser {
  /** @param {FactData} data */
  constructor(data) {
    this.data = data;
    this.kinds = byId("fact-kinds");
    this.list = byId("fact-list");
    this.doc = byId("fact-doc");
    this.page = byId("fact-page");
    /** @type {HTMLInputElement} */
    this.search = byId("fact-search");
    /** @type {HTMLButtonElement} */
    this.previous = byId("fact-prev");
    /** @type {HTMLButtonElement} */
    this.next = byId("fact-next");
    /** @type {string | null} */
    this.kind = null;
    this.offset = 0;
    this.size = 50;
    /** @type {Map<string, string>} */
    this.docs = new Map();
  }

  /**
   * @param {string} name
   * @param {number} count
   * @param {string} title
   * @param {string | null} kind
   */
  kindButton(name, count, title, kind) {
    const button = element("button", kind === null ? "active" : "");
    button.appendChild(element("span", "", name));
    button.appendChild(element("span", "n", String(count)));
    if (title) button.title = title;
    button.addEventListener("click", () => this.pick(kind, button));
    this.kinds.appendChild(button);
  }

  /**
   * @param {string | null} kind
   * @param {HTMLElement} button
   */
  pick(kind, button) {
    this.kind = kind;
    this.offset = 0;
    all("button", this.kinds).forEach((b) => b.classList.toggle("active", b === button));
    this.render();
  }

  matching() {
    const kind = this.kind;
    const text = this.search.value.toLowerCase();
    return this.data.facts.filter((f) => {
      if (kind && f.k !== kind) return false;
      return !text || (f.k + " " + f.o + " " + JSON.stringify(f.f)).toLowerCase().indexOf(text) >= 0;
    });
  }

  /** @param {Fact} fact */
  item(fact) {
    const item = element("div", "fact");
    const head = element("div");
    const fields = element("dl");
    head.appendChild(element("strong", "", fact.k));
    head.appendChild(document.createTextNode(" "));
    if (fact.u) {
      const origin = /** @type {HTMLAnchorElement} */ (element("a", "origin", fact.o));
      origin.href = fact.u;
      origin.target = "_blank";
      origin.rel = "noopener";
      head.appendChild(origin);
    } else {
      head.appendChild(element("span", "origin muted", fact.o));
    }
    Object.entries(fact.f).forEach(([key, value]) => {
      if (value === null || value === "" || value === false || (Array.isArray(value) && !value.length)) return;
      fields.appendChild(element("dt", "", key));
      fields.appendChild(element("dd", "", typeof value === "string" ? value : JSON.stringify(value)));
    });
    item.appendChild(head);
    item.appendChild(fields);
    return item;
  }

  render() {
    const found = this.matching();
    const last = Math.min(this.offset + this.size, found.length);
    this.doc.textContent = this.kind
      ? /** @type {string} */ (this.docs.get(this.kind))
      : "Every fact, in the order the stages found them.";
    this.list.textContent = "";
    found.slice(this.offset, last).forEach((fact) => this.list.appendChild(this.item(fact)));
    this.page.textContent = found.length ? this.offset + 1 + " to " + last + " of " + found.length : "No fact matches.";
    this.previous.disabled = this.offset === 0;
    this.next.disabled = last >= found.length;
  }

  start() {
    this.kindButton("All facts", this.data.facts.length, "", null);
    this.data.kinds.forEach((entry) => {
      this.docs.set(entry[0], entry[2]);
      this.kindButton(entry[0], entry[1], entry[2], entry[0]);
    });
    this.previous.addEventListener("click", () => {
      this.offset = Math.max(0, this.offset - this.size);
      this.render();
    });
    this.next.addEventListener("click", () => {
      this.offset += this.size;
      this.render();
    });
    this.search.addEventListener("input", () => {
      this.offset = 0;
      this.render();
    });
    this.render();
  }
}

// Trees open and close with the arrow keys, as they do elsewhere: on a focused summary, Right opens its details
// and Left closes them, or, already closed, moves to the summary of the details around it.
function walkTreesWithArrows() {
  document.addEventListener("keydown", (event) => {
    const summary = event.target;
    if (!(summary instanceof HTMLElement) || summary.tagName !== "SUMMARY") return;
    const details = /** @type {HTMLDetailsElement} */ (summary.parentElement);
    if (event.key === "ArrowRight" && !details.open) {
      details.open = true;
      event.preventDefault();
    } else if (event.key === "ArrowLeft") {
      const outer = details.parentElement && details.parentElement.closest("details");
      if (details.open) details.open = false;
      else if (outer) /** @type {HTMLElement} */ (outer.querySelector("summary")).focus();
      event.preventDefault();
    }
  });
}

followSections();
walkTreesWithArrows();
setUpFilters();
window.addEventListener("hashchange", openLinkedResult);
openLinkedResult();
new FactBrowser(JSON.parse(/** @type {string} */ (byId("facts-data").textContent))).start();
