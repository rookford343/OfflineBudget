import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { bankSyncApi } from "../api";
import { parseServerDateTime } from "../lib/utils";

/** "today 7:00 AM", "yesterday 3:00 PM", otherwise "Oct 27 7:00 AM". */
export function friendlyTime(iso: string, now: Date = new Date()): string {
  const d = parseServerDateTime(iso);
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  const dayStart = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((dayStart(now) - dayStart(d)) / 86400000);
  if (days === 0) return `today ${time}`;
  if (days === 1) return `yesterday ${time}`;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${time}`;
}

function sameDay(a: string, b: string): boolean {
  return parseServerDateTime(a).toDateString() === parseServerDateTime(b).toDateString();
}

const PROVIDER_LABEL: Record<string, string> = { plaid: "Plaid", simplefin: "SimpleFIN" };

/**
 * One compact line: when bank data was last pulled successfully, per
 * connection. "Successfully" comes from the backend's last_success_at (the
 * newest stamp on the connection's active links, which only a committed
 * import writes), not last_synced_at, which a failed run also stamps.
 */
export default function BankSyncStatusLine({ accounts, cards }: { accounts: any[]; cards: any[] }) {
  const { data: connections = [] } = useQuery<any[]>({ queryKey: ["bank-connections"], queryFn: bankSyncApi.status });
  const live = connections.filter((c) => c.status !== "disconnected" && (c.links ?? []).some((l: any) => l.is_active));
  if (live.length === 0) return null;

  const accountName = new Map(accounts.map((a) => [a.id, a.name]));
  const cardName = new Map(cards.map((c) => [c.id, c.name]));
  const label = (c: any) => {
    const names = (c.links ?? [])
      .filter((l: any) => l.is_active)
      .map((l: any) =>
        (l.local_account_id && accountName.get(l.local_account_id))
        || (l.local_credit_card_id && cardName.get(l.local_credit_card_id))
        || l.simplefin_account_name);
    return `${[...new Set(names)].join(", ")} (${PROVIDER_LABEL[c.provider] ?? c.provider})`;
  };

  const newest = live.map((c) => c.last_success_at).filter(Boolean).sort().pop() as string | undefined;

  return (
    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
      <span>{newest ? `Bank data updated ${friendlyTime(newest)}` : "Bank data not pulled yet"}</span>
      {live.map((c) => {
        const failing = !!c.last_error || c.status === "error";
        return (
          <span key={c.id} className="inline-flex items-center gap-1">
            <span aria-hidden className="text-gray-300 dark:text-gray-600">·</span>
            {failing ? (
              <Link to="/settings/accounts" title={c.last_error ?? "Sync failing"}
                className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 hover:underline">
                {label(c)}
                <AlertTriangle size={12} aria-label="Sync failing" />
                {c.last_success_at
                  ? `last good: ${friendlyTime(c.last_success_at)}`
                  : `sync failing: ${String(c.last_error ?? "error").slice(0, 60)}`}
              </Link>
            ) : (
              <>
                {label(c)}
                <CheckCircle2 size={12} className="text-emerald-500" aria-label="Synced" />
                {/* Only when it lags the headline time by a day or more, so
                    an older pull isn't hidden behind the newest one. */}
                {c.last_success_at && newest && !sameDay(c.last_success_at, newest)
                  && <span className="text-gray-400">{friendlyTime(c.last_success_at)}</span>}
                {!c.last_success_at && <span className="text-gray-400">not pulled yet</span>}
              </>
            )}
          </span>
        );
      })}
    </p>
  );
}
