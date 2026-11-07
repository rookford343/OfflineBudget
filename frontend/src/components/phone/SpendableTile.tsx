import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";

interface Props {
  weekly: number;
  today: number;
  onPace: boolean;
  hidden: boolean;
}

/** Spendable this week and today, coloured by pace like the desktop tile. */
export default function SpendableTile({ weekly, today, onPace, hidden }: Props) {
  const tone = onPace ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";
  const sign = (n: number) => (n < 0 ? "−" : "");
  return (
    <div className="card">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-gray-600 dark:text-gray-300">Spendable this week</span>
        <b className={`text-lg tabular-nums ${tone}`}>{maskIfHidden(hidden, `${sign(weekly)}${fmt(Math.abs(weekly))}`)}</b>
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-3">
        <span className="text-sm text-gray-600 dark:text-gray-300">Spendable today</span>
        <b className={`text-lg tabular-nums ${tone}`}>
          {maskIfHidden(hidden, `${sign(today)}${fmt(Math.abs(today))}`)}/day
        </b>
      </div>
      <p className={`mt-1 text-xs ${tone}`}>{onPace ? "on pace" : "over pace"}</p>
    </div>
  );
}
