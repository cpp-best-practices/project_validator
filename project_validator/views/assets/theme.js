(function () {
  var root = document.documentElement, key = "pv-theme";
  var saved = null;
  try { saved = localStorage.getItem(key); } catch (e) {}
  if (saved) root.dataset.theme = saved;
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".theme-toggle");
    if (!button) return;
    var dark = root.dataset.theme ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem(key, root.dataset.theme); } catch (e) {}
  });
})();
