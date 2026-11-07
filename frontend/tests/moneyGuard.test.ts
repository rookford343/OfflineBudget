import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "fs";
import { join, relative } from "path";

/**
 * Guard against money math creeping back into the browser.
 *
 * "The frontend displays backend figures and does no money math"
 * (docs/architecture.md). This scans frontend/src/**\/*.{ts,tsx} for:
 *
 * 1. a `.reduce(` whose callback adds or subtracts and touches a money figure,
 * 2. a `+` / `-` between `parseFloat(...)` / `Number(...)` results,
 * 3. a `+` / `-` between two "money locals" (per-file taint: a `const`/`let`
 *    whose name or initializer mentions a money identifier, or one derived from
 *    another tainted local), or between a money local and a parse call or
 *    money-named property (`discBudget - disc`, `actual - projected`),
 * 4. `+=` / `-=` accumulating a money local or a parsed money figure,
 * 5. a write to an object key that accumulates anything but a literal
 *    (`bucket[k] += amt`, `obj[k] = (obj[k] ?? 0) + amt`): a per-key money sum
 *    whose operands the taint pass cannot see (callback parameters).
 *
 * Money identifiers: amount, balance, pending, actual, budget, committed,
 * flexible, income, spent, available, total, ... Sort comparators are ignored.
 * Fix a hit by moving the figure to the backend and displaying the field.
 * Allowlist it only when it is presentational (a percent-of-total, share-of-pie
 * or percent-change ratio over figures the backend already sent, decision (c)),
 * chart sampling, or a draft preview. Every entry needs a reason; an entry that
 * no longer matches a hit fails the stale-entry test, so this list only shrinks.
 *
 * Known evasions: arithmetic on function parameters or object fields never
 * assigned to a local, taint that crosses files, and a figure named without
 * one of the identifiers. Review catches those.
 */

// Keyed "path under frontend/src:snippet of the offending statement" -> reason.
const ALLOWED: Record<string, string> = {
  "components/TransactionsCalendar.tsx:const dayNet = dayTxns.reduce":
    "sign only: picks the green or red dot on a calendar day; no figure is displayed",
  "lib/bonusSplit.ts:const moved = legs.reduce":
    "live preview of an unsaved bonus-allocation form; the backend (bonus_allocation.py) applies the real split on save",
  "pages/Import.tsx:totalAmount: indices.reduce":
    "pre-import review: totals the rows as the user is editing them, before anything is saved; draft preview, never reuse post-save",
  "lib/bonusSplit.ts:remainingCents -= amtCents;":
    "live preview of an unsaved bonus-allocation form (same function as above); draft preview, never reuse post-save",
  "pages/Spending.tsx:const total = pieData.reduce":
    "decision (c): denominator of a pie slice's share label over values the backend already sent",
  "pages/Spending.tsx:else cmp = Number(a.total) - Number(b.total);":
    "sort comparator written as an assignment; orders rows, produces no figure",
  "pages/settings/BonusAllocationSection.tsx:const total = upcoming.reduce":
    "draft preview: sizes the unsaved allocation form against the upcoming bonuses; the backend applies the real split on save",
  "pages/Import.tsx:if (Math.abs(txnAmt - recurAmt) < 0.01) return null;":
    "draft check: decides whether to offer 'Update to' by comparing the row being imported with the linked item's amount; the difference is never displayed",
  "pages/Dashboard.tsx:? ((last - refToday) / Math.abs(refToday)) * 100":
    "decision (c): percent change between two figures the backend already sent",
  "pages/Dashboard.tsx:return prev === 0 ? null : ((cur - prev) / prev) * 100;":
    "decision (c): percent change between two figures the backend already sent",
};

const MONEY = [
  "amount", "balance", "current_balance", "balance_due", "pending", "actual",
  "budget", "committed", "flexible", "income", "spent", "available", "total",
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

const OPERAND = String.raw`[A-Za-z_$][\w$.]*(?:\([^()]*\))?`;
const BINARY = new RegExp(String.raw`(${OPERAND})\s*(?<![+\-])[+-](?![+\-=>])\s*(?=(${OPERAND}))`, "g");
const MONEY_PROP = new RegExp(String.raw`\.\w*(${MONEY.join("|")})\w*$`, "i");
const DECL = /\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(.*)$/;

// `obj[k] += x` and `obj[k] = (obj[k] ?? 0) + x` (also `|| 0`, or no default).
const KEY_ACCUMULATE = [
  /[\w$.]+\[[^\]]+\]\s*[-+]=\s*([^;]*)/,
  /([\w$.]+\[[^\]]+\])\s*=\s*\(?\s*\1\s*(?:(?:\?\?|\|\|)\s*0\s*)?\)?\s*[-+]\s*([^;]*)/,
];
// A plain count or step (`+= 1`, `+ 0.5`, a string), not a figure.
const LITERAL = /^(\d+(\.\d+)?|["'`].*)\s*[,;)]*$/;

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

  // Pass 1: taint. A local is a money local when its name or initializer
  // mentions money, or the initializer uses another money local.
  const taint = new Set<string>();
  const mentionsTaint = (text: string) => [...taint].some((t) => new RegExp(String.raw`\b${t}\b`).test(text));
  const isComment = (l: string) => /^\s*(\*|\/\/|\/\*)/.test(l);
  for (const l of lines) {
    if (isComment(l)) continue;
    const d = DECL.exec(l);
    if (d && (mentionsMoney(d[1]) || mentionsMoney(d[2]) || mentionsTaint(d[2]))) taint.add(d[1]);
  }

  const moneyish = (operand: string): boolean =>
    taint.has(operand) || /^(parseFloat|Number)\(/.test(operand) && mentionsMoney(operand) ||
    MONEY_PROP.test(operand.replace(/\(.*$/, ""));

  const re = /\.reduce\(/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    const call = callText(src, m.index + ".reduce".length);
    const first = lineOf(m.index);
    const statement = lines[first] + " " + call;
    if (ARITH.test(call.replace(/=>/g, "")) && (mentionsMoney(statement) || mentionsTaint(call))) {
      hits.push(lines[first].trim());
    }
  }
  for (const l of lines) {
    // A sort comparator (`b.x - a.x`) orders rows; it produces no figure.
    if (/\.(sort|toSorted)\(/.test(l) || isComment(l)) continue;
    if (PARSE_ARITH.test(l) && mentionsMoney(l)) { hits.push(l.trim()); continue; }
    let found = false;
    BINARY.lastIndex = 0;
    let b: RegExpExecArray | null;
    while ((b = BINARY.exec(l))) {
      BINARY.lastIndex = b.index + b[0].length;  // resume at the second operand so `a - b - c` sees b - c
      if (moneyish(b[1]) && moneyish(b[2])) { found = true; break; }
    }
    if (!found) {
      const acc = /([A-Za-z_$][\w$]*)\s*[-+]=\s*(.*)$/.exec(l);
      if (acc && !/^[`"']/.test(acc[2].trim()) && (taint.has(acc[1]) || moneyish(acc[2].trim().split(/[\s;,)]/)[0] ?? "") ||
        (/(parseFloat|Number)\(/.test(acc[2]) && mentionsMoney(acc[2])))) found = true;
    }
    if (!found && KEY_ACCUMULATE.some((r) => { const k = r.exec(l); return k && !LITERAL.test(k[k.length - 1].trim()); })) found = true;
    if (found) hits.push(l.trim());
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

  test("flags subtraction between money locals (the three moved lines)", () => {
    const lines = [
      'const disc = parseFloat(overview.discretionary_actual ?? "0");\nconst discBudget = parseFloat(overview.discretionary_budgeted ?? "0");\nconst left = discBudget - disc;',
      'const projected = parseFloat(item.amount || "0");\nconst actual = override ? parseFloat(override.actual_amount) : null;\nconst variance = actual !== null ? actual - projected : 0;',
      'const forecastClose = parseFloat(q.close_balance);\nconst savedBalance = q.quarter_end_checkpoint != null ? parseFloat(q.quarter_end_checkpoint) : undefined;\nconst delta = savedBalance !== undefined ? savedBalance - forecastClose : null;',
    ];
    for (const sample of lines) expect(findViolations(sample)).toHaveLength(1);
  });

  test("flags loop accumulation of a money local", () => {
    const sample = "let total = parseFloat(first.amount);\nfor (const r of rows) { total += parseFloat(r.amount); }";
    expect(findViolations(sample).length).toBeGreaterThan(0);
  });

  test("flags per-key money accumulation, both spellings", () => {
    const sample = [
      "Object.entries(m).forEach(([label, amt]) => {",
      "  bucket[label] += parseFloat(amt);",
      "  totals[label] = (totals[label] ?? 0) + amt;",
      "  byDate[d.date] = (byDate[d.date] || 0) + parseFloat(d.projected_balance);",
      "});",
    ].join("\n");
    expect(findViolations(sample)).toHaveLength(3);
  });

  test("allows counting per key and plain key assignment", () => {
    const sample = [
      "counts[k] += 1;",
      "counts[k] = (counts[k] ?? 0) + 1;",
      "byId[r.id] = r.amount;",
      "const next = obj[k] + 1;",
    ].join("\n");
    expect(findViolations(sample)).toEqual([]);
  });

  test("allows subtraction of non-money locals", () => {
    const sample = "const end = parseFloat(range.end);\nconst start = parseFloat(range.start);\nconst width = end - start;\nconst rows = count - 1;";
    expect(findViolations(sample)).toEqual([]);
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
