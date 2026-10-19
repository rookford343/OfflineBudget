import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, checkingLevelApi } from "../../api";
import { byName } from "../../lib/selectOptions";
import { bodyFromDraft, draftFromRule, sourceAccounts, type CheckingLevelDraft } from "../../lib/checkingLevel";

/** "Keep checking at the right level": top up the primary checking account
 *  from savings when the forecast says it would dip too low, and -- only
 *  while saving each month -- sweep what it holds above a ceiling into
 *  savings once a month. Both run on the same check day in the forecast. */
export default function CheckingLevelSection({ savingsStrategy }: { savingsStrategy: string }) {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  // Same pick as the Forecast page's default account.
  const checking = byName(accounts.filter((a: any) => a.type === "checking"))[0];
  const others = sourceAccounts(byName(accounts.filter((a: any) => a.is_active !== false)), checking?.id);
  const defaultFrom = others.find((a: any) => a.type === "savings")?.id ?? others[0]?.id;

  const { data: rule, isSuccess } = useQuery({
    queryKey: ["checking-level", checking?.id],
    queryFn: () => checkingLevelApi.get(checking!.id),
    enabled: !!checking,
  });

  const [draft, setDraft] = useState<CheckingLevelDraft | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (isSuccess) setDraft(draftFromRule(rule, defaultFrom)); }, [isSuccess, rule, defaultFrom]);

  const saveMut = useMutation({
    mutationFn: (d: CheckingLevelDraft) => checkingLevelApi.put(bodyFromDraft(d, checking!.id)),
    onSuccess: () => {
      ["forecast-quarters", "forecast-multi-year", "forecast-risk", "checking-level"]
        .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (!checking || !draft) return null;
  const set = (patch: Partial<CheckingLevelDraft>) => setDraft({ ...draft, ...patch });
  const savingMonthly = savingsStrategy === "save_monthly";
  const accountOptions = others.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>);
  const errorDetail = (saveMut.error as any)?.response?.data?.detail;

  return (
    <div className="pt-3 border-t border-gray-100 dark:border-gray-700" role="group" aria-label="Keep checking at the right level">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Keep checking at the right level</span>
          <p className="text-xs text-gray-400">
            For {checking.name}. Checking holds what bills need; the forecast moves money in from savings before it would run low.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={draft.is_active}
          aria-label="Top-up rule on or off"
          onClick={() => set({ is_active: !draft.is_active })}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors shrink-0 ${draft.is_active ? "bg-indigo-600" : "bg-gray-200 dark:bg-gray-600"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${draft.is_active ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div><label className="label" htmlFor="cl-from">Top up from</label>
          <select id="cl-from" className="input text-sm" value={draft.from_account_id}
            onChange={(e) => set({ from_account_id: e.target.value })}>
            <option value="">Choose an account</option>
            {accountOptions}
          </select></div>
        <div><label className="label" htmlFor="cl-threshold">when it would drop below $</label>
          <input id="cl-threshold" type="number" step="1" className="input text-sm" value={draft.action_threshold}
            onChange={(e) => set({ action_threshold: e.target.value })} /></div>
        <div><label className="label" htmlFor="cl-floor">back up to $</label>
          <input id="cl-floor" type="number" step="1" className="input text-sm" value={draft.target_floor}
            onChange={(e) => set({ target_floor: e.target.value })} /></div>
        <div><label className="label" htmlFor="cl-increment">in steps of $</label>
          <input id="cl-increment" type="number" step="1" min="1" className="input text-sm" value={draft.increment}
            onChange={(e) => set({ increment: e.target.value })} /></div>
        <div><label className="label" htmlFor="cl-day">check on day</label>
          <input id="cl-day" type="number" min="1" max="28" className="input text-sm" value={draft.check_day}
            onChange={(e) => set({ check_day: e.target.value })} /></div>
      </div>

      {savingMonthly && (
        <div className="mt-3 space-y-2">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" className="h-4 w-4 accent-indigo-600" aria-label="Sweep extra to savings"
              checked={draft.sweep_on} onChange={() => set({ sweep_on: !draft.sweep_on })} />
            Sweep extra to savings
          </label>
          <p className="text-xs text-gray-400">Once a month on the check day, never right after a paycheck.</p>
          {draft.sweep_on && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div><label className="label" htmlFor="cl-ceiling">keep at most $</label>
                <input id="cl-ceiling" type="number" step="1" className="input text-sm" value={draft.sweep_ceiling}
                  onChange={(e) => set({ sweep_ceiling: e.target.value })} /></div>
              <div><label className="label" htmlFor="cl-sweep-to">move the extra to</label>
                <select id="cl-sweep-to" className="input text-sm" value={draft.sweep_to_account_id}
                  onChange={(e) => set({ sweep_to_account_id: e.target.value })}>
                  <option value="">Choose an account</option>
                  {accountOptions}
                </select></div>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3">
        <button className="btn-secondary text-sm" disabled={saveMut.isPending || !draft.from_account_id}
          onClick={() => saveMut.mutate(draft)}>
          {saveMut.isPending ? "Saving…" : "Save"}
        </button>
        {saved && <span className="text-sm text-green-600 dark:text-green-400">Saved!</span>}
      </div>
      {saveMut.isError && (
        <p className="text-xs text-red-500 mt-1" role="alert">
          {typeof errorDetail === "string"
            ? errorDetail
            : "Couldn't save. \"Back up to\" must be at least \"drop below\", steps above $0, the day 1–28, and \"keep at most\" above \"back up to\" with an account to move it to."}
        </p>
      )}
    </div>
  );
}
