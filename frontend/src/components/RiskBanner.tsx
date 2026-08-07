import { AlertTriangle, ArrowRightLeft } from "lucide-react";
import { fmt } from "../lib/utils";

interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
  transfer_triggered?: boolean;
  transfer_date?: string | null;
  transfer_amount?: string | null;
  transfer_from?: string | null;
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
}

export function RiskBanner({ risk }: { risk: Risk | undefined }) {
  if (!risk) return null;

  const showAlert = risk.at_risk && risk.date && risk.amount != null;
  const showTransfer = risk.transfer_triggered && risk.transfer_date && risk.transfer_amount != null;

  if (!showAlert && !showTransfer) return null;

  return (
    <div className="flex flex-col gap-2">
      {showTransfer && (
        <div className="card border-orange-200 dark:border-orange-700 bg-orange-50/60 dark:bg-orange-900/20">
          <div className="flex items-start gap-3">
            <ArrowRightLeft size={18} className="text-orange-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-orange-900 dark:text-orange-200 text-sm">
                {`Needs a ${fmt(parseFloat(risk.transfer_amount!))} transfer from ${risk.transfer_from} around ${formatDate(risk.transfer_date!)}`}
              </p>
              <p className="text-xs text-orange-700 dark:text-orange-400 mt-0.5">
                Modeled automatically to keep the account above its action threshold.
              </p>
            </div>
          </div>
        </div>
      )}
      {showAlert && (
        <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-red-900 dark:text-red-200 text-sm">
                {parseFloat(risk.threshold) > 0
                  ? `Projected to drop below ${fmt(parseFloat(risk.threshold))} on ${formatDate(risk.date!)}`
                  : `Projected to go negative on ${formatDate(risk.date!)}`}
              </p>
              <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
                Projected balance: <strong>{fmt(parseFloat(risk.amount!))}</strong>
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
