import { fmt } from "./utils";
import { maskIfHidden } from "../store/balanceVisibility";

export function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
}

const money = (hidden: boolean, amount: string) => maskIfHidden(hidden, fmt(parseFloat(amount)));

export function transferHeadline(
  transferAmount: string,
  transferFrom: string | null | undefined,
  transferDate: string,
  hidden: boolean,
): string {
  return `Needs a ${money(hidden, transferAmount)} transfer from ${transferFrom} around ${formatDate(transferDate)}`;
}

export function suggestionHeadline(
  suggestedAmount: string,
  suggestedDate: string,
  alreadyPlanned: boolean | undefined,
  hidden: boolean,
): string {
  return alreadyPlanned
    ? `Still short: top up by ${money(hidden, suggestedAmount)} by ${formatDate(suggestedDate)}`
    : `Suggested: move ${money(hidden, suggestedAmount)} to cover this by ${formatDate(suggestedDate)}`;
}

export function alertHeadline(
  threshold: string,
  status: "ok" | "warning" | "danger" | undefined,
  date: string,
  hidden: boolean,
): string {
  if (parseFloat(threshold) <= 0) return `Projected to go negative on ${formatDate(date)}`;
  if (status === "danger") {
    return `Drops below your ${money(hidden, threshold)} cushion on ${formatDate(date)} and goes negative within the window`;
  }
  return `Projected to drop below your ${money(hidden, threshold)} cushion on ${formatDate(date)}`;
}

export function projectedBalanceText(amount: string, hidden: boolean): string {
  return money(hidden, amount);
}
