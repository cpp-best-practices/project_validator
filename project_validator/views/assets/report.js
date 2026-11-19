// The HTML report's behaviour: the navigation follows the section on screen, the results filter by status and text,
// a link to a result opens it, and the facts (JSON in #facts-data) are browsed by kind and searched.
"use strict";

function element(tag, cls, text) {
  var node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function followSections() {
  var links = Array.prototype.slice.call(document.querySelectorAll(".topbar nav a"));
  var sections = links.map(function (a) { return document.querySelector(a.getAttribute("href")); });
  function spy() {
    var current = 0;
    sections.forEach(function (s, i) { if (s && s.getBoundingClientRect().top < 120) current = i; });
    links.forEach(function (a, i) { a.classList.toggle("active", i === current); });
  }
  document.addEventListener("scroll", spy, { passive: true });
  spy();
}

function visible(node) { return node.style.display !== "none"; }

function filterResults(shown, search) {
  var text = (search && search.value || "").toLowerCase();
  document.querySelectorAll("details.check").forEach(function (d) {
    var ok = shown[d.dataset.status] !== false && (!text || d.dataset.search.indexOf(text) >= 0);
    d.style.display = ok ? "" : "none";
  });
  document.querySelectorAll(".category").forEach(function (c) {
    var checks = c.querySelectorAll("details.check");
    c.style.display = Array.prototype.some.call(checks, visible) ? "" : "none";
  });
}

function setUpFilters() {
  var shown = {}, search = document.getElementById("result-search");
  var buttons = document.querySelectorAll(".filter");
  buttons.forEach(function (b) { shown[b.dataset.filter] = b.getAttribute("aria-pressed") === "true"; });
  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      shown[b.dataset.filter] = !shown[b.dataset.filter];
      b.setAttribute("aria-pressed", String(shown[b.dataset.filter]));
      filterResults(shown, search);
    });
  });
  if (search) search.addEventListener("input", function () { filterResults(shown, search); });
  filterResults(shown, search);
}

function openLinkedResult() {
  var target = location.hash && document.getElementById(location.hash.slice(1));
  if (target && target.tagName === "DETAILS") { target.open = true; target.style.display = ""; }
}

function FactBrowser(data) {
  this.data = data;
  this.kinds = document.getElementById("fact-kinds");
  this.list = document.getElementById("fact-list");
  this.doc = document.getElementById("fact-doc");
  this.page = document.getElementById("fact-page");
  this.search = document.getElementById("fact-search");
  this.kind = null;
  this.offset = 0;
  this.size = 50;
  this.docs = {};
}

FactBrowser.prototype.kindButton = function (name, count, title, kind) {
  var self = this, button = element("button", kind === null ? "active" : "");
  button.appendChild(element("span", "", name));
  button.appendChild(element("span", "n", String(count)));
  if (title) button.title = title;
  button.addEventListener("click", function () { self.pick(kind, button); });
  this.kinds.appendChild(button);
};

FactBrowser.prototype.pick = function (kind, button) {
  this.kind = kind;
  this.offset = 0;
  this.kinds.querySelectorAll("button").forEach(function (b) { b.classList.toggle("active", b === button); });
  this.render();
};

FactBrowser.prototype.matching = function () {
  var kind = this.kind, text = (this.search.value || "").toLowerCase();
  return this.data.facts.filter(function (f) {
    if (kind && f.k !== kind) return false;
    return !text || (f.k + " " + f.o + " " + JSON.stringify(f.f)).toLowerCase().indexOf(text) >= 0;
  });
};

FactBrowser.prototype.item = function (fact) {
  var item = element("div", "fact"), head = element("div"), fields = element("dl");
  head.appendChild(element("strong", "", fact.k));
  head.appendChild(document.createTextNode(" "));
  var origin = element(fact.u ? "a" : "span", fact.u ? "origin" : "origin muted", fact.o);
  if (fact.u) { origin.href = fact.u; origin.target = "_blank"; origin.rel = "noopener"; }
  head.appendChild(origin);
  Object.keys(fact.f).forEach(function (key) {
    var value = fact.f[key];
    if (value === null || value === "" || value === false || (Array.isArray(value) && !value.length)) return;
    fields.appendChild(element("dt", "", key));
    fields.appendChild(element("dd", "", typeof value === "string" ? value : JSON.stringify(value)));
  });
  item.appendChild(head);
  item.appendChild(fields);
  return item;
};

FactBrowser.prototype.render = function () {
  var self = this, found = this.matching(), last = Math.min(this.offset + this.size, found.length);
  this.doc.textContent = this.kind ? this.docs[this.kind] || "" : "Every fact, in the order the stages found them.";
  this.list.textContent = "";
  found.slice(this.offset, last).forEach(function (fact) { self.list.appendChild(self.item(fact)); });
  this.page.textContent = found.length ? (this.offset + 1) + " to " + last + " of " + found.length : "No fact matches.";
  document.getElementById("fact-prev").disabled = this.offset === 0;
  document.getElementById("fact-next").disabled = last >= found.length;
};

FactBrowser.prototype.start = function () {
  var self = this;
  this.kindButton("All facts", this.data.facts.length, "", null);
  this.data.kinds.forEach(function (entry) {
    self.docs[entry[0]] = entry[2];
    self.kindButton(entry[0], entry[1], entry[2], entry[0]);
  });
  document.getElementById("fact-prev").addEventListener("click", function () {
    self.offset = Math.max(0, self.offset - self.size);
    self.render();
  });
  document.getElementById("fact-next").addEventListener("click", function () { self.offset += self.size; self.render(); });
  this.search.addEventListener("input", function () { self.offset = 0; self.render(); });
  this.render();
};

followSections();
setUpFilters();
window.addEventListener("hashchange", openLinkedResult);
openLinkedResult();
new FactBrowser(JSON.parse(document.getElementById("facts-data").textContent)).start();
