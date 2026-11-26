export type LowestBalanceRow = { label: string; amount: number; date: string; isLookaheadRow: boolean };

/** [{ label, amount, date, isLookaheadRow }, ...] (0, 1, or 2 rows) for the
 *  "lowest balance" lines under the Household Snapshot cards. Ported
 *  line-for-line from backend/services/summary_generator.py's
 *  _lowest_balance_rows (lines 52-78), plus the move-to-checking condition
 *  from _move_to_checking_line (lines 32-39) applied by the caller, so the
 *  dashboard and the daily email never disagree on which rows show, in what
 *  order, or whether next month's low and the 3-month low get merged.
 *  `isLookaheadRow` marks the row Python's `_is_lookahead_row` would pick out
 *  (the one covering "the next 3 months") -- only that row gets the
 *  cushion/danger coloring and warning phrase. */
export function lowestBalanceRows(snapshot: any): LowestBalanceRow[] {
  const lookaheadDate: string | null = snapshot.lookahead_minimum_date ?? null;
  const nextMonthDate: string | null = snapshot.next_month_minimum_date ?? null;
  if (lookaheadDate == null && nextMonthDate == null) return [];

  const quarterRow: LowestBalanceRow | null = lookaheadDate != null
    ? { label: "Lowest in the next 3 months", amount: parseFloat(snapshot.lookahead_minimum), date: lookaheadDate, isLookaheadRow: true }
    : null;

  if (nextMonthDate == null) return quarterRow ? [quarterRow] : [];

  const nmLabel = snapshot.next_month_label || "next month";
  const nextMonthAmount = parseFloat(snapshot.next_month_minimum);
  const same = quarterRow != null && nextMonthDate === lookaheadDate && nextMonthAmount === quarterRow.amount;
  if (same) {
    return [{
      label: `Lowest next month (${nmLabel}) and in the next 3 months`,
      amount: nextMonthAmount,
      date: nextMonthDate,
      isLookaheadRow: true,
    }];
  }

  const rows: LowestBalanceRow[] = [{
    label: `Lowest next month (${nmLabel})`,
    amount: nextMonthAmount,
    date: nextMonthDate,
    isLookaheadRow: false,
  }];
  if (quarterRow) rows.push(quarterRow);
  return rows;
}
