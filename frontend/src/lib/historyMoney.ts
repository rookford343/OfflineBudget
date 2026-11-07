import { fmt } from "./utils";
import { maskIfHidden } from "../store/balanceVisibility";

// Display only: the backend's signed decimal string picks the sign, fmt()
// formats the magnitude. No arithmetic on the figure.
export function signedMoney(hidden: boolean, v: string | null, plus: boolean): string {
  if (v == null) return "";
  const neg = v.startsWith("-");
  const body = maskIfHidden(hidden, fmt(neg ? v.slice(1) : v));
  return `${neg ? "−" : plus ? "+" : ""}${body}`;
}

// A grouped cause's item amount: the figure as the bank listed it, no sign.
export function itemMoney(hidden: boolean, v: string): string {
  return maskIfHidden(hidden, fmt(v.startsWith("-") ? v.slice(1) : v));
}
