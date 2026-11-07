import { useQuery } from "@tanstack/react-query";
import { accountsApi } from "../api";

export interface PendingBalance {
  /** The bank's live pending rows for this account (empty when none). */
  pending: any[];
  posted: number;
  /** Posted plus every live pending row, as figured by the backend. */
  afterPending: number;
}

/**
 * The backend's account balances (GET /accounts/balances), one query shared
 * by the sidebar and the Dashboard Checking card. Keyed under "accounts" so
 * every mutation that invalidates the accounts also refreshes it.
 */
export function useAccountBalances() {
  return useQuery<any>({
    queryKey: ["accounts", "balances"],
    queryFn: accountsApi.balances,
    staleTime: 30_000,
  });
}

/** Per-account balances with pending, read from the backend. Display only. */
export function usePendingBalances(): (account: any) => PendingBalance {
  const { data } = useAccountBalances();
  const byId = new Map<number, any>((data?.accounts ?? []).map((b: any) => [b.account_id, b]));
  return (account: any) => {
    const b = byId.get(account.id);
    if (!b) {
      const posted = parseFloat(account.current_balance);
      return { pending: [], posted, afterPending: posted };
    }
    return { pending: b.pending, posted: parseFloat(b.posted), afterPending: parseFloat(b.after_pending) };
  };
}
