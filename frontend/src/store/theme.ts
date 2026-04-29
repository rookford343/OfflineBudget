const KEY = "budget_theme";

export function getTheme(): "dark" | "light" {
  return (localStorage.getItem(KEY) as "dark" | "light") ?? "light";
}

export function setTheme(dark: boolean): void {
  const theme = dark ? "dark" : "light";
  localStorage.setItem(KEY, theme);
  applyTheme(dark);
}

export function applyTheme(dark: boolean): void {
  document.documentElement.classList.toggle("dark", dark);
}

export function initTheme(): void {
  applyTheme(getTheme() === "dark");
}
