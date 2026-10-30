import { useQueries } from "@tanstack/react-query";
import { accountsApi } from "../api";

export interface PendingBalance {
  /** The bank's pending rows for this account (empty when none). */
  pending: any[];
  posted: number;
  /** posted + pending amounts (negative = money out): the balance as if
   *  every pending item goes through. Display-only. */
  afterPending: number;
}

/**
 * One fetch path for every checking account's bank-pending snapshot, shared
 * (same query keys) by the Dashboard Checking card, the sidebar accounts
 * list and the Transactions page. Non-checking accounts aren't fetched: the
 * endpoint only ever returns rows for a Plaid-fed checking account.
 */
export function usePendingBalances(accounts: any[]): (account: any) => PendingBalance {
  const checking = accounts.filter((a) => a.type === "checking" && a.is_active !== false);
  const results = useQueries({
    queries: checking.map((a) => ({
      queryKey: ["account-pending-transactions", a.id],
      queryFn: () => accountsApi.pendingTransactions(a.id),
    })),
  });
  const byId = new Map<number, any[]>();
  checking.forEach((a, i) => byId.set(a.id, (results[i]?.data as any[] | undefined) ?? []));
  return (account: any) => {
    const pending = byId.get(account.id) ?? [];
    const posted = parseFloat(account.current_balance);
    return { pending, posted, afterPending: posted + pending.reduce((s, p) => s + parseFloat(p.amount), 0) };
  };
}
