import { parseServerDateTime } from "./utils";

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
