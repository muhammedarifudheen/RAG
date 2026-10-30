/** The colour theme: dark ("midnight glass", the default) or light, kept in this browser
 * and applied before the first paint by the script in the page head. */

export type Theme = "dark" | "light";

export const THEME_KEY = "atlas-theme";

/** Runs in the page head, before anything is drawn: the theme and contrast chosen. */
export const THEME_SCRIPT =
  "try{var d=document.documentElement;" +
  "if(localStorage.getItem('atlas-theme')==='light')d.dataset.theme='light';" +
  "if(localStorage.getItem('atlas-contrast')==='high')d.dataset.contrast='high'}catch(e){}";

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  if (theme === "light") document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
  try {
    if (theme === "light") window.localStorage.setItem(THEME_KEY, "light");
    else window.localStorage.removeItem(THEME_KEY);
  } catch {
    // This page only.
  }
  window.dispatchEvent(new Event("atlas-theme"));
}
