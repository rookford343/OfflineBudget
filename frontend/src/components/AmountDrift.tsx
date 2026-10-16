import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { TrendingUp } from "lucide-react";

/** "Mon D" from an ISO date, parsed at noon so a UTC-negative timezone can't
 *  shift the date back a day. */
function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type Action = "update" | "keep" | "varies";

/**
 * "Amounts changed?": recurring expenses whose latest linked payment differs
 * from the planned amount (backend services/amount_drift.py). Nothing changes
 * until the user answers: Update takes the latest payment as the amount from
 * now on, Keep stays quiet until a newer payment posts, and "Varies" stops
 * asking for that item. A bill whose payments swing on their own is offered
 * only Keep or Varies, since no single number fits it.
 */
export default function AmountDrift() {
  const qc = useQueryClient();
  const { data: items = [] } = useQuery<any[]>({
    queryKey: ["amount-drift"],
    queryFn: recurringApi.amountDrift,
  });

  const answerMut = useMutation({
    mutationFn: ({ id, action }: { id: number; action: Action }) => recurringApi.answerAmountDrift(id, action),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["amount-drift"] });
      // An updated amount moves every forecast and budget figure built on it,
      // the same set the Recurring page's own edit invalidates.
      qc.invalidateQueries({ queryKey: ["recurring"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      qc.invalidateQueries({ queryKey: ["budget-snapshot"] });
      qc.invalidateQueries({ queryKey: ["recurring-month-summary"] });
      qc.invalidateQueries({ queryKey: ["recurring-breakdown"] });
    },
  });

  if (items.length === 0) return null;

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
        <TrendingUp size={16} className="text-amber-500" /> Amounts changed?
      </h3>
      {answerMut.isError && (
        <p className="text-xs text-red-500 dark:text-red-400 mb-2" role="alert">
          Couldn't save that answer. Try again.
        </p>
      )}
      <div className="space-y-1">
        {items.map((d: any) => {
          const busy = answerMut.isPending && answerMut.variables?.id === d.recurring_item_id;
          const answer = (action: Action) => answerMut.mutate({ id: d.recurring_item_id, action });
          return (
            <div
              key={d.recurring_item_id}
              className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-gray-50 dark:border-gray-800 last:border-0"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{d.name}</p>
                <p className="text-xs text-gray-400">
                  {d.varies
                    ? `recent payments ${d.recent_amounts.map((a: string) => fmt(a)).join(", ")} · planned ${fmt(d.planned_amount)}`
                    : `paid ${fmt(d.latest_amount)} on ${shortDate(d.latest_date)} · planned ${fmt(d.planned_amount)}`}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {d.varies ? (
                  <button className="btn-primary py-1 px-2 text-xs disabled:opacity-50" disabled={busy}
                    onClick={() => answer("varies")} title="This bill swings on its own; stop asking about it">
                    Varies, stop asking
                  </button>
                ) : (
                  <button className="btn-primary py-1 px-2 text-xs disabled:opacity-50" disabled={busy}
                    onClick={() => answer("update")} title={`Use ${fmt(d.latest_amount)} from now on`}>
                    Update to {fmt(d.latest_amount)}
                  </button>
                )}
                <button className="btn-secondary py-1 px-2 text-xs disabled:opacity-50" disabled={busy}
                  onClick={() => answer("keep")} title="Keep the planned amount until another payment posts">
                  Keep {fmt(d.planned_amount)}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
