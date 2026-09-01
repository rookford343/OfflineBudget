import { useState, useEffect } from "react";

const KEY = "budget_balances_hidden";
const EVENT = "balances-hidden-changed";

// Hidden by default -- a fresh browser (no stored preference yet) should not
// show account balances until the user opts in, not the other way around.
export function getBalancesHidden(): boolean {
  const stored = localStorage.getItem(KEY);
  return stored === null ? true : stored === "1";
}

function setBalancesHidden(hidden: boolean): void {
  localStorage.setItem(KEY, hidden ? "1" : "0");
}

// Single global switch, toggleable from the header icon or the Settings
// Preferences tab -- both call this, both stay in sync via the event below.
export function toggleBalancesHidden(): void {
  const next = !getBalancesHidden();
  setBalancesHidden(next);
  window.dispatchEvent(new CustomEvent(EVENT));
}

// Every page that displays a balance calls this instead of duplicating the
// read-plus-event-listener boilerplate. Mirrors the `nav-order-changed`
// pattern already used elsewhere in this app for cross-component sync
// without a reload (this codebase has no React Context anywhere -- a plain
// window event is the established way two mounted components agree on one
// piece of shared state).
export function useBalancesHidden(): boolean {
  const [hidden, setHidden] = useState(getBalancesHidden);
  useEffect(() => {
    const handler = () => setHidden(getBalancesHidden());
    window.addEventListener(EVENT, handler);
    return () => window.removeEventListener(EVENT, handler);
  }, []);
  return hidden;
}

// A fixed-width mask so a hidden dollar figure doesn't visibly resize its
// container or shift adjacent layout -- long enough to plausibly cover a
// large balance, short enough not to look like a placeholder/loading state.
const MASK = "••••••";

export function maskIfHidden(hidden: boolean, text: string): string {
  return hidden ? MASK : text;
}
