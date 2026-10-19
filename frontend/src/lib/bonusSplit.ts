/** Pure client-side mirror of backend/services/bonus_allocation.py's
 * split_bonus(), used only to preview "Next bonus: $X to Money Market, …"
 * before saving. The backend remains the source of truth for the real
 * transfers injected into the forecast -- this never writes anything.
 *
 * Works in integer cents throughout (not floating-point dollars) so a
 * percent-of-bonus calculation can't drift off the backend's Decimal
 * arithmetic the way repeated float dollar math would.
 */

export type AllocationStepKind = "fixed" | "percent" | "rest";

export type AllocationStep = {
  account_id: number;
  kind: AllocationStepKind;
  value: string | null;
  round_to: string | null;
};

export type SplitLeg = { account_id: number; amount: number };

const dollarsToCents = (n: number): number => Math.round(n * 100);
const centsToDollars = (c: number): number => c / 100;

/** True floor to a multiple of `toDollars` when set and > 0, otherwise a
 * true floor to whole cents -- never rounds up, matching backend round_down. */
function roundDownCents(amountCents: number, toDollars: number | null): number {
  if (toDollars != null && toDollars > 0) {
    const stepCents = dollarsToCents(toDollars);
    if (stepCents > 0) return Math.floor(amountCents / stepCents) * stepCents;
  }
  return Math.floor(amountCents);
}

const asNumber = (v: string | null): number | null => (v == null || v === "" ? null : Number(v));

/** Waterfall `total` (dollars) across `steps` in order, returning
 * (account_id, amount-in-dollars) legs. Whatever isn't moved stays in
 * checking -- mirrors split_bonus() exactly, including the shortfall
 * short-circuit and the "never move more than total" guarantee (every leg
 * is bounded by `remainingCents`, which starts at totalCents and only ever
 * shrinks). */
export function splitBonus(
  total: number,
  steps: AllocationStep[],
  shortfallAccountId: number | null,
  shortfallRoundTo: string | null,
): SplitLeg[] {
  const totalCents = dollarsToCents(total);
  const fixedNeededCents = steps
    .filter((s) => s.kind === "fixed")
    .reduce((sum, s) => sum + dollarsToCents(asNumber(s.value) ?? 0), 0);

  if (totalCents < fixedNeededCents && shortfallAccountId != null) {
    const amtCents = roundDownCents(totalCents, asNumber(shortfallRoundTo));
    return amtCents > 0 ? [{ account_id: shortfallAccountId, amount: centsToDollars(amtCents) }] : [];
  }

  const legs: SplitLeg[] = [];
  let remainingCents = totalCents;
  for (const s of steps) {
    let amtCents: number;
    if (s.kind === "fixed") {
      const valueCents = dollarsToCents(asNumber(s.value) ?? 0);
      amtCents = roundDownCents(Math.min(valueCents, remainingCents), asNumber(s.round_to));
    } else if (s.kind === "percent") {
      const pct = asNumber(s.value) ?? 0;
      const rawCents = (totalCents * pct) / 100;
      amtCents = Math.min(roundDownCents(rawCents, asNumber(s.round_to)), remainingCents);
    } else {
      amtCents = roundDownCents(remainingCents, asNumber(s.round_to));
    }
    remainingCents -= amtCents;
    if (amtCents === 0) continue;
    legs.push({ account_id: s.account_id, amount: centsToDollars(amtCents) });
  }
  return legs;
}

/** "$25,000.00 to Money Market, $23,000.00 to Savings, $656.00 stays in
 * checking." -- the preview line's sentence, given the split and a name
 * lookup for each destination account. */
export function describeSplit(
  total: number,
  legs: SplitLeg[],
  nameOf: (accountId: number) => string,
  fmt: (n: number) => string,
): string {
  const parts = legs.filter((l) => l.amount > 0).map((l) => `${fmt(l.amount)} to ${nameOf(l.account_id)}`);
  const moved = legs.reduce((sum, l) => sum + l.amount, 0);
  const remainder = Math.max(0, total - moved);
  if (remainder > 0 || parts.length === 0) {
    parts.push(`${fmt(remainder)} stays in checking`);
  }
  return `${parts.join(", ")}.`;
}
