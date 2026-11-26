import { Wallet } from "lucide-react";
import HowCalculated from "../HowCalculated";
import WhatChanged from "../WhatChanged";
import { VerificationFlagButton } from "../VerificationFlagButton";
import { WeeklyLowsChart } from "./WeeklyLowsChart";
import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";
import { lowestBalanceRows } from "../../lib/lowestBalanceRows";
import { safetyMarginTone, spendableTone, type WeeklyLow } from "../../lib/weeklyLows";

export const SPENDABLE_HELP = "How much you can spend on everyday things (groceries, eating out, shopping) between now and the end of the week, after bills, savings, and tithing are already set aside.\n\nGoes down as you spend. If it's negative, you've spent more than this week's share — it'll say \"over pace\" and show what to pull back.";
export const MARGIN_HELP = "The lowest your checking account is projected to go over the next 3 months, after also setting aside the credit card bills still coming due this month.\n\nPositive means that's how much room you have above $0 before you'd need to pull from savings. Negative means the plan already dips into savings, even before anything unexpected happens — worth a closer look before a big purchase.";

const shortDate = (iso: string) =>
  new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

export function SnapshotHero({
  snapshot,
  primaryCheckingId,
  hidden,
  isWide,
}: {
  snapshot: any;
  primaryCheckingId?: number;
  hidden: boolean;
  isWide: boolean;
}) {
  const m = (n: number) => maskIfHidden(hidden, fmt(n));
  // Sign goes inside the mask so a hidden figure never reveals its sign.
  const signed = (n: number) => maskIfHidden(hidden, (n < 0 ? "−" : "") + fmt(Math.abs(n)));
  const pendingCount = Number(snapshot.pending_cards_count ?? 0);
  const smWeekly = parseFloat(snapshot.safety_margin_weekly);
  const smToday = parseFloat(snapshot.safety_margin_today);
  const smTone = safetyMarginTone(smWeekly);
  const spWeekly = parseFloat(snapshot.left_to_spend_weekly);
  const spTone = spendableTone(spWeekly);
  const spendToday = parseFloat(snapshot.spendable_today);
  const lows: WeeklyLow[] = Array.isArray(snapshot.weekly_lows) ? snapshot.weekly_lows : [];
  const status = snapshot.lookahead_status ?? "ok";

  return (
    <div className="max-w-[960px] rounded-xl border border-line bg-card p-4 md:p-5">
      <div className="flex items-center gap-2 mb-3">
        <Wallet size={16} className="text-accent" />
        <h3 className="font-semibold text-ink">Household Snapshot</h3>
        <WhatChanged metric={{ key: "leftover", title: "Leftover" }} />
        <VerificationFlagButton
          feature="household_snapshot"
          referenceType="account"
          referenceId={primaryCheckingId}
          observed={{
            left_to_spend: snapshot.left_to_spend,
            left_to_spend_weekly: snapshot.left_to_spend_weekly,
            safety_margin: snapshot.safety_margin,
            safety_margin_weekly: snapshot.safety_margin_weekly,
          }}
          expectedFields={[
            { key: "left_to_spend", label: "Left to Spend (monthly)" },
            { key: "safety_margin", label: "Safety Margin (monthly)" },
          ]}
          className="ml-auto"
        />
      </div>
      <div className={isWide ? "grid grid-cols-[auto_auto] justify-start gap-x-16" : "grid grid-cols-1 gap-4"}>
        <div>
          <p className="text-[13px] text-muted mb-1 flex items-center gap-1">
            Safety Margin (this week)
            <HowCalculated
              title="Safety Margin"
              explanations={[snapshot.explain?.safety_margin, snapshot.explain?.safety_margin_week, snapshot.explain?.safety_margin_today]}
              helpText={MARGIN_HELP}
            />
            <WhatChanged metric={{ key: "safety_margin", title: "Safety Margin (month)" }} />
          </p>
          <p
            data-testid="sm-figure"
            className={`text-4xl md:text-[40px] font-bold tabular-nums ${smTone === "danger" ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}
          >
            {m(smWeekly)}
          </p>
          <p className="text-[13px] text-muted mt-1">
            {signed(smToday)}/day
          </p>
          <p className="text-[13px] text-muted">{m(parseFloat(snapshot.safety_margin))} this month</p>
          {pendingCount > 0 && (
            <p className="text-[13px] text-muted">
              Includes pending charges on {pendingCount} card{pendingCount === 1 ? "" : "s"} ({m(parseFloat(snapshot.pending_cards_total))})
            </p>
          )}
          {parseFloat(snapshot.savings_pull_needed) > 0 && (
            <p className="text-sm font-medium text-warn-text mt-2">
              Pull {m(parseFloat(snapshot.savings_pull_needed))} from savings
            </p>
          )}
        </div>
        <div>
          <p className="text-[13px] text-muted mb-1 flex items-center gap-1">
            Spendable this week
            <HowCalculated
              title="Spendable this week"
              explanations={[snapshot.explain?.left_to_spend, snapshot.explain?.spendable_week, snapshot.explain?.spendable_today]}
              helpText={SPENDABLE_HELP}
            />
            <WhatChanged metric={{ key: "left_to_spend", title: "Spendable this month" }} />
          </p>
          <p
            data-testid="sp-figure"
            className={`text-[22px] font-bold tabular-nums ${spTone === "caution" ? "text-warn-figure" : "text-emerald-600 dark:text-emerald-400"}`}
          >
            {m(spWeekly)}
          </p>
          <p className="text-[13px] text-muted mt-1">
            {/* Signed on purpose: over pace, this is how much a day must come back. */}
            {signed(spendToday)}/day ·{" "}
            <span className={snapshot.on_pace ? "" : "text-warn-text font-medium"}>
              {snapshot.on_pace ? "on pace" : "over pace"}
            </span>
          </p>
          <p className="text-[13px] text-muted">{m(parseFloat(snapshot.left_to_spend))} this month</p>
        </div>
      </div>

      {lows.length > 0 && (
        <div className="mt-4">
          <p className="text-[13px] uppercase tracking-wide text-muted mb-2">
            Checking low point each week · next 3 months
          </p>
          <WeeklyLowsChart lows={lows} hidden={hidden} cushion={parseFloat(snapshot.safety_cushion)} />
        </div>
      )}

      {lowestBalanceRows(snapshot).map((row, i) => {
        const warn = row.isLookaheadRow && status !== "ok";
        const figureClass = warn
          ? status === "danger"
            ? "text-red-600 dark:text-red-400"
            : "text-warn-figure"
          : row.amount < 0
            ? "text-red-600 dark:text-red-400"
            : "text-ink";
        return (
          <div key={row.label}>
            <p className={`text-[13px] text-muted ${i === 0 ? "mt-3" : "mt-1"}`}>
              {row.label}:{" "}
              <span className={`font-semibold tabular-nums ${figureClass}`}>{m(row.amount)}</span> on {shortDate(row.date)}{" "}
              {row.isLookaheadRow && (
                <span className="inline-flex align-middle">
                  <HowCalculated title="3-month lowest point" explanations={[snapshot.explain?.lookahead_minimum]} />
                  <WhatChanged metric={{ key: "lookahead_minimum", title: "3-month lowest point" }} />
                </span>
              )}
              {warn && (
                <span className={`block mt-0.5 font-medium ${figureClass}`}>
                  {status === "danger"
                    ? "below $0"
                    : `below your ${m(parseFloat(snapshot.safety_cushion))} cushion`}
                </span>
              )}
            </p>
            {i === 0 && snapshot.next_month_minimum_date && parseFloat(snapshot.move_to_checking_needed) > 0 && (
              <p className="text-[13px] text-red-600 dark:text-red-400 mt-1">
                Move {m(parseFloat(snapshot.move_to_checking_needed))} into checking by{" "}
                {new Date(
                  new Date(snapshot.next_month_minimum_date + "T12:00:00").getFullYear(),
                  new Date(snapshot.next_month_minimum_date + "T12:00:00").getMonth(),
                  1,
                ).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
