import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "fs";
import { join, relative } from "path";

/**
 * Guard against money math creeping back into the browser.
 *
 * "The frontend displays backend figures and does no money math"
 * (docs/architecture.md). This scans frontend/src/**\/*.{ts,tsx} for two
 * shapes of arithmetic on money figures:
 *
 * 1. a `.reduce(` whose callback adds or subtracts, and
 * 2. a `+` / `-` between `parseFloat(...)` / `Number(...)` results,
 *
 * when the statement mentions a money identifier (amount, balance, pending,
 * actual, budget, ...). Fix a hit by moving the figure to the backend and
 * displaying the field. Allowlist it only when it is presentational (a
 * percent-of-total or share-of-pie ratio over figures the backend already sent,
 * decision (c)), chart sampling, or a consistency check that is never shown.
 * Every entry needs a reason; an entry that no longer matches a hit fails the
 * stale-entry test, so this list only shrinks.
 *
 * Known evasions: arithmetic through a temp variable, `for` loops with `+=`,
 * and a figure named without one of the identifiers below. Review catches those.
 */

// Keyed "path under frontend/src:snippet of the offending statement" -> reason.
const ALLOWED: Record<string, string> = {
  "components/TransactionsCalendar.tsx:const dayNet = dayTxns.reduce":
    "sign only: picks the green or red dot on a calendar day; no figure is displayed",
  "lib/bonusSplit.ts:const moved = legs.reduce":
    "live preview of an unsaved bonus-allocation form; the backend (bonus_allocation.py) applies the real split on save",
  "pages/Import.tsx:totalAmount: indices.reduce":
    "pre-import review: totals the rows as the user is editing them, before anything is saved",
};

const MONEY = [
  "amount", "balance", "current_balance", "balance_due", "pending", "actual",
  "budget", "committed", "flexible", "income", "spent", "available",
];

/** The text of a call starting at `open` (the index of its "("), balanced. */
function callText(src: string, open: number): string {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) return src.slice(open, i + 1);
  }
  return src.slice(open);
}

// An operator between two operands: `a + b`, `a - b`, `s + Number(x)`. Not `++`, `+=` alone, a sign (`-1`), or `=>`.
const ARITH = /[\w)\]]\s*(?<![+\-])[+-](?![+\-=>])\s*[\w(\[]/;
const PARSE_ARITH = /\b(parseFloat|Number)\([^()]*\)\s*(?<![+\-])[+-](?![+\-=])\s*(parseFloat|Number)\(/;

function mentionsMoney(text: string): boolean {
  const t = text.toLowerCase();
  return MONEY.some((m) => t.includes(m));
}

export function findViolations(src: string): string[] {
  const lines = src.split("\n");
  const lineStart: number[] = [];
  let off = 0;
  for (const l of lines) { lineStart.push(off); off += l.length + 1; }
  const lineOf = (idx: number) => {
    let lo = 0, hi = lines.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (lineStart[mid] <= idx) lo = mid; else hi = mid - 1; }
    return lo;
  };
  const hits: string[] = [];
  const re = /\.reduce\(/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    const call = callText(src, m.index + ".reduce".length);
    const first = lineOf(m.index);
    const statement = lines[first] + " " + call;
    if (ARITH.test(call.replace(/=>/g, "")) && mentionsMoney(statement)) hits.push(lines[first].trim());
  }
  for (const l of lines) {
    // A sort comparator (`b.x - a.x`) orders rows; it produces no figure.
    if (/\.(sort|toSorted)\(/.test(l)) continue;
    if (PARSE_ARITH.test(l) && mentionsMoney(l)) hits.push(l.trim());
  }
  return hits;
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sourceFiles(p);
    return /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

const SRC = join(import.meta.dir, "..", "src");

/** Every hit as "path:statement", and the allowlist keys each one is covered by. */
function scan() {
  const all: { key: string; allowedBy: string | undefined }[] = [];
  for (const file of sourceFiles(SRC)) {
    const rel = relative(SRC, file);
    for (const hit of findViolations(readFileSync(file, "utf8"))) {
      const key = `${rel}:${hit}`;
      all.push({ key, allowedBy: Object.keys(ALLOWED).find((k) => key.includes(k)) });
    }
  }
  return all;
}

describe("frontend does no money math", () => {
  test("no reduce or parseFloat arithmetic on money figures", () => {
    const bad = scan().filter((h) => !h.allowedBy).map((h) => h.key);
    expect(bad, "move these figures to the backend (docs/architecture.md), do not allowlist them").toEqual([]);
  });

  test("allowlist has no stale entries", () => {
    const used = new Set(scan().map((h) => h.allowedBy));
    const stale = Object.keys(ALLOWED).filter((k) => !used.has(k));
    expect(stale, "allowlist entries that no longer match a hit (delete them)").toEqual([]);
  });

  test("every allowlist entry says why", () => {
    for (const [k, reason] of Object.entries(ALLOWED)) expect(reason.length, k).toBeGreaterThan(10);
  });
});

describe("guard self-tests", () => {
  test("flags a reduce that sums money", () => {
    const sample = "const total = rows.reduce((s, r) => s + parseFloat(r.amount), 0);";
    expect(findViolations(sample)).toHaveLength(1);
  });

  test("flags a multi-line reduce and parseFloat subtraction", () => {
    const sample = [
      "const left = items.reduce(",
      "  (acc, i) => acc - Number(i.budget),",
      "  0);",
      "const gap = parseFloat(a.balance) - parseFloat(b.balance);",
    ].join("\n");
    expect(findViolations(sample)).toHaveLength(2);
  });

  test("ignores a sort comparator", () => {
    expect(findViolations("rows.sort((a, b) => parseFloat(b.actual) - parseFloat(a.actual));")).toEqual([]);
  });

  test("allows a percent-of-total ratio and a reduce that is not money", () => {
    const sample = [
      "const pct = maxTotal > 0 ? (Number(m.total) / maxTotal) * 100 : 0;",
      "const n = rows.reduce((c, r) => c + 1, 0);",
      "const label = rows.reduce((a, r) => a + r.name, '');",
    ].join("\n");
    expect(findViolations(sample)).toEqual([]);
  });
});
