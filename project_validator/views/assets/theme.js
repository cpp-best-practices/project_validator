// The light and dark themes: the one kept from the last visit, else the system's, switched by the theme button.
(function () {
  const root = document.documentElement;
  const key = "pv-theme";
  let saved = null;
  try {
    saved = localStorage.getItem(key);
  } catch {
    // storage refused (a private window, a sandboxed frame): the system's theme
  }
  if (saved) root.dataset.theme = saved;
  document.addEventListener("click", (event) => {
    const target = event.target;
    const button = target instanceof Element && target.closest(".theme-toggle");
    if (!button) return;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem(key, root.dataset.theme);
    } catch {
      // as above: the theme lasts until the page is left
    }
  });
})();
