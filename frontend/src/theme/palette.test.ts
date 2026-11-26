/**
 * Guards the named palette in index.css and the temporary indigo alias in
 * tailwind.config.js: exact values from the spec, and WCAG AA contrast in both themes.
 */
import { describe, expect, test } from "bun:test";
import { join } from "node:path";
import { contrastRatio } from "./contrast";

const root = join(import.meta.dir, "..", "..");
const css = await Bun.file(join(root, "src", "index.css")).text();
const tw = await Bun.file(join(root, "tailwind.config.js")).text();

const EXPECTED: Record<string, [string, string]> = {
  surface: ["#f8fafc", "#0b1220"],
  card: ["#ffffff", "#131c2e"],
  ink: ["#0f172a", "#e2e8f0"],
  muted: ["#64748b", "#94a3b8"],
  line: ["#e2e8f0", "#22304a"],
  bar: ["#cbd5e1", "#334155"],
  accent: ["#0f766e", "#2dd4bf"],
  "accent-strong": ["#0f766e", "#0f766e"],
  warn: ["#d97706", "#f59e0b"],
  "warn-text": ["#92400e", "#fcd34d"],
  "warn-figure": ["#b45309", "#fbbf24"],
  "warn-bg": ["#fef3c7", "#2a1a06"],
  "warn-line": ["#fde68a", "#5a3a0e"],
};

function block(selector: RegExp): Record<string, string> {
  const m = css.match(selector);
  if (!m) return {};
  const out: Record<string, string> = {};
  for (const v of m[1].matchAll(/--c-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[v[1]] = v[2].toLowerCase();
  return out;
}
const light = block(/:root\s*\{([^}]*)\}/);
const dark = block(/\.dark\s*\{([^}]*)\}/);
const themes = { light, dark };

describe("palette values", () => {
  for (const [token, [l, d]] of Object.entries(EXPECTED)) {
    test(`--c-${token} has the spec values`, () => {
      expect(light[token]).toBe(l);
      expect(dark[token]).toBe(d);
    });
  }
});

describe("palette contrast", () => {
  const body: [string, string][] = [
    ["ink", "card"],
    ["muted", "card"],
    ["muted", "surface"],
    ["accent", "card"],
    ["warn-text", "card"],
    ["warn-text", "warn-bg"],
  ];
  for (const [name, t] of Object.entries(themes)) {
    for (const [fg, bg] of body) {
      test(`${name}: ${fg} on ${bg} >= 4.5`, () => {
        expect(contrastRatio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
      });
    }
    test(`${name}: white on accent-strong >= 4.5`, () => {
      expect(contrastRatio("#ffffff", t["accent-strong"])).toBeGreaterThanOrEqual(4.5);
    });
    test(`${name}: warn-figure on card >= 3.0 (large text)`, () => {
      expect(contrastRatio(t["warn-figure"], t["card"])).toBeGreaterThanOrEqual(3.0);
    });
  }
});

describe("temporary indigo alias", () => {
  const m = tw.match(/indigo:\s*\{([^}]*)\}/);
  const scale: Record<string, string> = {};
  for (const v of (m?.[1] ?? "").matchAll(/(\d+):\s*"(#[0-9a-fA-F]{6})"/g)) scale[v[1]] = v[2];
  test("defines the full 50-950 scale", () => {
    expect(Object.keys(scale).sort()).toEqual(
      ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"].sort(),
    );
  });
  test.each(["600", "700"])("indigo-%s on white >= 4.5", (k) => {
    expect(contrastRatio(scale[k], "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
  test.each(["300", "400"])("indigo-%s on dark card >= 4.5", (k) => {
    expect(contrastRatio(scale[k], "#131c2e")).toBeGreaterThanOrEqual(4.5);
  });
});

describe("dark indigo text overrides", () => {
  const rules = [...css.matchAll(/\.dark \.text-indigo-\d+[^{]*\{\s*color:\s*([^;}]+?)\s*;?\s*\}/g)];
  const teal = new Set(["var(--c-accent)", "#5eead4", "#2dd4bf"]);
  test("rules exist", () => expect(rules.length).toBeGreaterThan(0));
  test("every rule uses a teal color, not a hard-coded indigo", () => {
    for (const r of rules) expect(teal.has(r[1].toLowerCase())).toBe(true);
  });
  test("each resolves to >= 4.5 on the dark card", () => {
    for (const r of rules) {
      const hex = r[1] === "var(--c-accent)" ? dark["accent"] : r[1];
      expect(contrastRatio(hex, dark["card"])).toBeGreaterThanOrEqual(4.5);
    }
  });
});
