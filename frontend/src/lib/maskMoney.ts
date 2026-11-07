/**
 * Hide every dollar figure inside free text (history summaries, calculation
 * notes) when "Hide balances" is on. Matches the app's own money shapes:
 * "$1,234.56", "−$1,234.56", "-$5", "+$50.00".
 */
export function maskMoneyText(hidden: boolean, text: string): string {
  return hidden ? text.replace(/[−+-]?\$[\d,]+(?:\.\d{1,2})?/g, "••••") : text;
}
