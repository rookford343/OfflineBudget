import { useState } from "react";
import { AlertTriangle, ArrowRightLeft } from "lucide-react";
import { fmt } from "../lib/utils";

interface SourceAccount {
  id: number;
  name: string;
}

interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
  transfer_triggered?: boolean;
  transfer_date?: string | null;
  transfer_amount?: string | null;
  transfer_from?: string | null;
  suggested_transfer_amount?: string | null;
  suggested_transfer_date?: string | null;
  suggested_transfer_from_account_id?: number | null;
  suggested_transfer_already_planned?: boolean;
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
}

export function RiskBanner({
  risk,
  sourceAccounts = [],
  onAcceptSuggestion,
}: {
  risk: Risk | undefined;
  sourceAccounts?: SourceAccount[];
  onAcceptSuggestion?: (amount: string, date: string, fromAccountId: number) => void;
}) {
  // The backend leaves suggested_transfer_from_account_id null whenever the
  // source is ambiguous (zero or 2+ savings accounts) rather than guessing.
  // Accepting has to resolve that before it creates a source-less transfer.
  const [pickedFromId, setPickedFromId] = useState("");

  if (!risk) return null;

  const showAlert = risk.at_risk && risk.date && risk.amount != null;
  const showTransfer = risk.transfer_triggered && risk.transfer_date && risk.transfer_amount != null;
  // already_planned no longer suppresses: the backend's amount is already net
  // of any accepted transfer, so a surviving suggestion is a genuine top-up.
  const showSuggestion = risk.at_risk && risk.suggested_transfer_amount != null && risk.suggested_transfer_date != null;

  const suggestedFromId = risk.suggested_transfer_from_account_id ?? null;
  const needsSourcePick = suggestedFromId === null;
  const resolvedFromId = suggestedFromId ?? (pickedFromId ? parseInt(pickedFromId) : null);

  if (!showAlert && !showTransfer && !showSuggestion) return null;

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
      {showSuggestion && onAcceptSuggestion && (
        <div className="card border-blue-200 dark:border-blue-700 bg-blue-50/60 dark:bg-blue-900/20">
          <div className="flex items-start gap-3">
            <ArrowRightLeft size={18} className="text-blue-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-blue-900 dark:text-blue-200 text-sm">
                {risk.suggested_transfer_already_planned
                  ? `Still short: top up by ${fmt(parseFloat(risk.suggested_transfer_amount!))} by ${formatDate(risk.suggested_transfer_date!)}`
                  : `Suggested: move ${fmt(parseFloat(risk.suggested_transfer_amount!))} to cover this by ${formatDate(risk.suggested_transfer_date!)}`}
              </p>
              <p className="text-xs text-blue-700 dark:text-blue-400 mt-0.5">
                {risk.suggested_transfer_already_planned
                  ? "You already have a transfer planned near this date, but it doesn't cover the whole dip."
                  : "You'll need to make this transfer yourself in your bank — accepting just plans it here."}
              </p>
              {needsSourcePick && (
                <label className="flex items-center gap-2 mt-2 text-xs text-blue-800 dark:text-blue-300">
                  Move from
                  <select
                    className="input w-auto text-xs py-1"
                    value={pickedFromId}
                    onChange={(e) => setPickedFromId(e.target.value)}
                  >
                    <option value="">Choose an account…</option>
                    {sourceAccounts.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </label>
              )}
              <button
                onClick={() => resolvedFromId !== null && onAcceptSuggestion(risk.suggested_transfer_amount!, risk.suggested_transfer_date!, resolvedFromId)}
                disabled={resolvedFromId === null}
                className="btn-primary btn-sm text-xs px-3 py-1.5 mt-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Accept
              </button>
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
