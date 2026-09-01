const KEY = "budget_balances_hidden";

// Hidden by default -- a fresh browser (no stored preference yet) should not
// show account balances until the user opts in, not the other way around.
export function getBalancesHidden(): boolean {
  const stored = localStorage.getItem(KEY);
  return stored === null ? true : stored === "1";
}

export function setBalancesHidden(hidden: boolean): void {
  localStorage.setItem(KEY, hidden ? "1" : "0");
}
