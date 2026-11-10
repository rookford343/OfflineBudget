import { useState, useEffect } from "react";

const KEY = "budget_theme";
const EVENT = "theme-changed";

export function getTheme(): "dark" | "light" {
  return (localStorage.getItem(KEY) as "dark" | "light") ?? "light";
}

export function applyTheme(dark: boolean): void {
  document.documentElement.classList.toggle("dark", dark);
  // The app picks its own theme (not the OS), so keep the browser chrome colour in step.
  document.querySelectorAll('meta[name="theme-color"]').forEach(m => m.setAttribute("content", dark ? "#111827" : "#f9fafb"));
}

export function initTheme(): void {
  applyTheme(getTheme() === "dark");
}

// Single global switch, toggleable from the sidebar header icon or the
// Settings Preferences tab -- both call this, both stay in sync via the
// event below (same pattern as balanceVisibility.ts's toggleBalancesHidden).
export function setTheme(dark: boolean): void {
  localStorage.setItem(KEY, dark ? "dark" : "light");
  applyTheme(dark);
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function toggleTheme(): void {
  setTheme(getTheme() !== "dark");
}

export function useIsDarkMode(): boolean {
  const [dark, setDark] = useState(() => getTheme() === "dark");
  useEffect(() => {
    const handler = () => setDark(getTheme() === "dark");
    window.addEventListener(EVENT, handler);
    return () => window.removeEventListener(EVENT, handler);
  }, []);
  return dark;
}
