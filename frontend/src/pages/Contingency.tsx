import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { ShieldCheck } from "lucide-react";

interface ContingencyCutItem {
  id: number;
  name: string;
  monthly_equivalent: string;
  is_paused: boolean;
}

interface ContingencyPlan {
  floor: string;
  emergency_fund_balance: string;
  surplus: string;
  cut_list: ContingencyCutItem[];
}

/** "What if income stopped" planning: the essential-spend floor (3x
 *  essential monthly burn) against the emergency fund's real balance, plus
 *  the non-essential items a scenario could pause to close any shortfall.
 *  All three numbers and the cut list come straight from the backend
 *  (GET /recurring/contingency) -- nothing is computed client-side. */
export default function Contingency() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery<ContingencyPlan>({
    queryKey: ["recurring-contingency"],
    queryFn: recurringApi.contingency,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["recurring-contingency"] });
  const pauseMut = useMutation({
    mutationFn: (itemId: number) => recurringApi.contingencyPause(itemId),
    onSuccess: invalidate,
  });
  const unpauseMut = useMutation({
    mutationFn: (itemId: number) => recurringApi.contingencyUnpause(itemId),
    onSuccess: invalidate,
  });
  const toggleBusy = pauseMut.isPending || unpauseMut.isPending;

  const surplus = data ? parseFloat(data.surplus) : 0;

  return (
    <div className="space-y-6 tap-44">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-1.5">
          <ShieldCheck size={18} className="text-indigo-500" /> Contingency Planning
        </h2>
        <p className="text-sm text-gray-500">What if income stopped — essential floor vs. emergency fund</p>
      </div>

      {isLoading && <p className="text-sm text-gray-400 py-4 text-center">Loading…</p>}

      {data && (
        <div className="card">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">3-Month Floor</p>
              <p className="text-lg font-bold tabular-nums text-gray-900 dark:text-white">{fmt(data.floor)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Emergency Fund</p>
              <p className="text-lg font-bold tabular-nums text-gray-900 dark:text-white">{fmt(data.emergency_fund_balance)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Surplus</p>
              {/* Same ternary Dashboard.tsx uses for Available (>=0 green,
                  negative red) -- surplus is the same kind of figure: good
                  when the fund covers the floor, a warning when it doesn't. */}
              <p className={`text-lg font-bold tabular-nums ${surplus >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                {fmt(data.surplus)}
              </p>
            </div>
          </div>
        </div>
      )}

      {data && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Non-Essential Expenses (cut if needed)</h3>
          {data.cut_list.length === 0 ? (
            <p className="text-sm text-gray-400 py-4 text-center">No non-essential recurring expenses</p>
          ) : (
            <div className="space-y-1.5">
              {data.cut_list.map((item) => (
                <div key={item.id} className="flex items-center justify-between py-1.5 border-b border-gray-50 dark:border-gray-800 last:border-0">
                  <span className={`text-sm ${item.is_paused ? "text-gray-400 line-through" : "text-gray-900 dark:text-white"}`}>
                    {item.name}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400">{fmt(item.monthly_equivalent)}/mo</span>
                    <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                      <input
                        type="checkbox"
                        checked={item.is_paused}
                        disabled={toggleBusy}
                        onChange={() => (item.is_paused ? unpauseMut.mutate(item.id) : pauseMut.mutate(item.id))}
                      />
                      Paused
                    </label>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
