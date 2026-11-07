import { parseServerDateTime } from "./utils";

export interface PendingCard {
  is_active?: boolean;
  pending_effective: string | number | null;
}

/** How many active cards carry pending charges, and their combined total.
 *  Per card, not per charge: the backend reports one effective pending figure
 *  per card. */
export function summarizePending(cards: PendingCard[]): { count: number; total: number } {
  let count = 0;
  let total = 0;
  for (const c of cards) {
    if (c.is_active === false || c.pending_effective == null) continue;
    const v = typeof c.pending_effective === "number" ? c.pending_effective : parseFloat(c.pending_effective);
    if (!Number.isFinite(v) || v === 0) continue;
    count += 1;
    total += v;
  }
  return { count, total };
}

/** Newest successful bank pull across live (not disconnected, with an active
 *  link) connections -- the same rule BankSyncStatusLine uses for its headline. */
export function lastBankSync(connections: any[]): Date | null {
  const times = connections
    .filter((c) => c.status !== "disconnected" && (c.links ?? []).some((l: any) => l.is_active))
    .map((c) => c.last_success_at as string | null | undefined)
    .filter((t): t is string => !!t)
    .sort();
  const newest = times.pop();
  return newest ? parseServerDateTime(newest) : null;
}
