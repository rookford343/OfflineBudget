/** The primary checking account: the one Forecast, Safety Margin and the
 * Wish List walk. Mirrors the backend's primary_checking — the accounts API
 * returns active accounts in id order, so the first active checking wins. */
export function primaryChecking<T extends { type: string; is_active?: boolean }>(
  accounts: readonly T[],
): T | undefined {
  return accounts.find((a) => a.type === "checking" && a.is_active !== false);
}
