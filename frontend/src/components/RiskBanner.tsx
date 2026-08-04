import { AlertTriangle } from "lucide-react";
import { fmt } from "../lib/utils";

interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
}

export function RiskBanner({ risk }: { risk: Risk | undefined }) {
  if (!risk || !risk.at_risk || !risk.date || risk.amount == null) return null;

  const dateLabel = new Date(risk.date + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
  const thresholdNum = parseFloat(risk.threshold);
  const label = thresholdNum > 0
    ? `Projected to drop below ${fmt(thresholdNum)} on ${dateLabel}`
    : `Projected to go negative on ${dateLabel}`;

  return (
    <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-red-900 dark:text-red-200 text-sm">{label}</p>
          <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
            Projected balance: <strong>{fmt(parseFloat(risk.amount))}</strong>
          </p>
        </div>
      </div>
    </div>
  );
}
