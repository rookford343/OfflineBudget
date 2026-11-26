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

export interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
  status?: "ok" | "warning" | "danger";
  transfer_triggered?: boolean;
  transfer_date?: string | null;
  transfer_amount?: string | null;
  transfer_from?: string | null;
  suggested_transfer_amount?: string | null;
  suggested_transfer_date?: string | null;
  suggested_transfer_from_account_id?: number | null;
  suggested_transfer_already_planned?: boolean;
}

// True when the banner would render at least one of its three cards.
export function riskHasContent(risk: Risk | null | undefined): boolean {
  if (!risk) return false;
  const showAlert = !!(risk.at_risk && risk.date && risk.amount != null);
  const showTransfer = !!(risk.transfer_triggered && risk.transfer_date && risk.transfer_amount != null);
  // already_planned no longer suppresses: the backend's amount is already net
  // of any accepted transfer, so a surviving suggestion is a genuine top-up.
  const showSuggestion = !!(
    risk.at_risk &&
    risk.suggested_transfer_amount != null &&
    risk.suggested_transfer_date != null
  );
  return showAlert || showTransfer || showSuggestion;
}

// A typed override must never be used while balances are hidden: the user
// cannot see the field, so Accept falls back to the backend's suggestion.
export function effectiveTransferAmount(
  hidden: boolean,
  override: string,
  suggested: string | null | undefined,
): string {
  if (hidden) return suggested ?? "";
  return override || suggested || "";
}
