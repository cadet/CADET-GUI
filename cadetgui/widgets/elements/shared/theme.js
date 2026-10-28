// The theme the stylesheet chose (--cg-theme on the widget's scope), so JS colours match CSS.
function isDark(node) {
  const theme = getComputedStyle(node).getPropertyValue("--cg-theme").trim();
  if (theme) return theme === "dark";
  return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
}
