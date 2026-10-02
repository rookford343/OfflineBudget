export type Payment = "cash" | "points" | "mix";
export type Pricing = "flat" | "per_day" | "per_night" | "per_person" | "per_person_day";
export type Category = "getting_there" | "staying" | "daily" | "before" | "while_there";
export type TripStatus = "planning" | "committed" | "done";

export interface WalletRow {
  id: number; name: string; kind: "bank" | "airline" | "hotel" | "other";
  balance: number; reserved: number; available: number;
  balance_updated_at: string | null; age_days: number | null; is_active: boolean; sort_order: number;
}
export interface PartnerRow {
  id: number; from_program_id: number; from_program_name: string; to_program_id: number;
  to_program_name: string; ratio: string; bonus_pct: string | null; bonus_ends_on: string | null;
  bonus_active: boolean;
}
export interface Suggestion {
  from_program_id: number; from_program_name: string; source_points: number;
  partner_points: number; bonus_pct: string | null;
}
export interface TripItem {
  id: number; category: Category; name: string; pricing: Pricing; unit_cash: string | null;
  payment: Payment; points_program_id: number | null; points_price: number | null;
  cash_copay: string; mix_cash: string | null; charge_date: string | null; card_id: number | null;
  transfer_from_program_id: number | null; transfer_points: number | null; is_paid: boolean;
  planned_expense_id: number | null; sort_order: number; multiplier: number; is_auto_buffer: boolean;
  cash_price: string; cash_owed: string; points_used: number; value_cpp: string | null;
  suggestion: Suggestion | null;
}
export interface PointsSummaryRow {
  program_id: number; name: string; needed: number; available: number; incoming: number; shortfall: number;
}
export interface TripSummary {
  id: number; name: string; destination: string | null; start_date: string; end_date: string;
  travelers: number; status: TripStatus; cash_total: string; cash_remaining: string;
  points_by_program: Record<string, number>; fund_goal_id: number | null;
  fund_current: string | null; fund_target: string | null;
}
export interface TripDetailData extends TripSummary {
  default_card_id: number | null; notes: string | null; items: TripItem[];
  points_summary: PointsSummaryRow[];
}

export const CATEGORY_LABEL: Record<Category, string> = {
  getting_there: "Getting there", staying: "Staying", daily: "Daily",
  before: "Before you go", while_there: "While there",
};
export const PRICING_HINT: Record<Pricing, string> = {
  flat: "", per_day: "per day", per_night: "per night", per_person: "per person",
  per_person_day: "per person / day",
};
export const pts = (n: number) => n.toLocaleString("en-US");
export const shortDate = (d: string) =>
  new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
