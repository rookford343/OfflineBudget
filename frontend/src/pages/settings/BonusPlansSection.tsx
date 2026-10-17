import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi, bonusPlansApi, recurringApi } from "../../api";
import { fmt } from "../../lib/utils";
import { Plus, Trash2 } from "lucide-react";
import { ConfirmDialog } from "../../components/ConfirmDialog";

type Draft = {
  id?: number;
  recurring_item_id: string;
  target_pct: string;
  salary_lag_years: string;
  withholding_pct: string;
  years: { year: string; gross_amount: string }[];
};

const blank: Draft = { recurring_item_id: "", target_pct: "20", salary_lag_years: "1", withholding_pct: "", years: [] };

/** Salary settings and annual bonus plans. Each plan pays through a yearly
 *  income item (created on the Recurring page); the forecast adds that
 *  year's net on the item's date and counts the gross toward the Social
 *  Security wage base. */
export default function BonusPlansSection() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const { data: plans = [] } = useQuery<any[]>({ queryKey: ["bonus-plans"], queryFn: bonusPlansApi.list });
  const { data: items = [] } = useQuery<any[]>({ queryKey: ["recurring"], queryFn: () => recurringApi.list(false) });
  const yearlyIncome = items.filter((i: any) => i.type === "income" && i.frequency === "yearly" && i.is_active);

  const [salary, setSalary] = useState("");
  const [salaryYear, setSalaryYear] = useState("");
  const [raise, setRaise] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [salarySaved, setSalarySaved] = useState(false);
  const [deletePlan, setDeletePlan] = useState<any | null>(null);

  useEffect(() => {
    if (me) {
      setSalary(me.annual_salary ?? "");
      setSalaryYear(me.annual_salary_year != null ? String(me.annual_salary_year) : String(new Date().getFullYear()));
      setRaise(me.annual_raise_pct ?? "");
    }
  }, [me]);

  const invalidate = () => {
    ["me", "bonus-plans", "recurring", "forecast-quarters", "forecast-multi-year", "forecast-risk", "budget-snapshot"]
      .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  const salaryMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { invalidate(); setSalarySaved(true); setTimeout(() => setSalarySaved(false), 2000); },
  });
  const saveMut = useMutation({
    mutationFn: (d: Draft) => {
      const body = {
        recurring_item_id: parseInt(d.recurring_item_id),
        target_pct: d.target_pct, salary_lag_years: parseInt(d.salary_lag_years), withholding_pct: d.withholding_pct,
        years: d.years.filter((y) => y.year && y.gross_amount).map((y) => ({ year: parseInt(y.year), gross_amount: y.gross_amount })),
      };
      return d.id ? bonusPlansApi.update(d.id, body) : bonusPlansApi.create(body);
    },
    onSuccess: () => { invalidate(); setDraft(null); },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => bonusPlansApi.remove(id),
    onSuccess: () => { invalidate(); setDeletePlan(null); },
  });

  const edit = (p: any) => setDraft({
    id: p.id, recurring_item_id: String(p.recurring_item_id), target_pct: String(p.target_pct),
    salary_lag_years: String(p.salary_lag_years), withholding_pct: String(p.withholding_pct),
    years: p.years.map((y: any) => ({ year: String(y.year), gross_amount: String(y.gross_amount) })),
  });

  return (
    <div className="space-y-3 pt-6 mt-6 border-t border-gray-100 dark:border-gray-800">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">Salary & bonuses</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Bonuses are forecast on their pay date at the net amount, and their gross counts toward the Social Security wage base.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
        <div><label className="label">Base salary (gross)</label>
          <input type="number" className="input" value={salary} onChange={(e) => setSalary(e.target.value)} /></div>
        <div><label className="label">For year</label>
          <input type="number" className="input" value={salaryYear} onChange={(e) => setSalaryYear(e.target.value)} /></div>
        <div><label className="label">Expected yearly raise %</label>
          <input type="number" step="0.1" className="input" value={raise} onChange={(e) => setRaise(e.target.value)} /></div>
      </div>
      <div className="flex items-center gap-3">
        <button className="btn-secondary text-sm" disabled={salaryMut.isPending}
          onClick={() => salaryMut.mutate({ annual_salary: salary || null, annual_salary_year: salaryYear ? parseInt(salaryYear) : null, annual_raise_pct: raise || null })}>
          Save salary
        </button>
        {salarySaved && <span className="text-sm text-green-600">Saved!</span>}
      </div>
      {salaryMut.isError && (
        <p className="text-xs text-red-500" role="alert">
          Couldn't save salary settings. Raise must be 0–25% and the year 2000–2100.
        </p>
      )}

      <div className="space-y-2">
        {plans.map((p: any) => (
          <div key={p.id} className="rounded-lg border border-gray-100 dark:border-gray-800 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-gray-900 dark:text-white">{p.item_name}</p>
              <div className="flex gap-2">
                <button className="text-xs text-indigo-500 hover:underline" onClick={() => edit(p)}>Edit</button>
                <button className="text-gray-400 hover:text-red-500" aria-label={`Delete ${p.item_name} plan`}
                  onClick={() => setDeletePlan(p)}><Trash2 size={14} /></button>
              </div>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {p.target_pct}% of {p.salary_lag_years === 1 ? "last year's" : `the salary ${p.salary_lag_years} years back`} · {p.withholding_pct}% withheld
            </p>
            <div className="text-xs text-gray-600 dark:text-gray-300 mt-1 flex flex-wrap gap-x-4">
              {p.upcoming.map((u: any) => (
                <span key={u.year}>{u.year}: {u.gross != null ? `${fmt(u.gross)} gross → ${fmt(u.net)} net` : "salary not set"}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {draft ? (
        <div className="rounded-lg border border-indigo-200 dark:border-indigo-900 p-3 space-y-2 max-w-xl">
          <div><label className="label">Paid through (yearly income item)</label>
            <select className="input" value={draft.recurring_item_id}
              onChange={(e) => setDraft({ ...draft, recurring_item_id: e.target.value })}>
              <option value="">Choose…</option>
              {yearlyIncome.map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
            {yearlyIncome.length === 0 && (
              <p className="text-xs text-amber-600 mt-1">Add a yearly income item on the Recurring page first (frequency Yearly, its pay date).</p>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div><label className="label">Target %</label>
              <input type="number" step="0.1" className="input" value={draft.target_pct}
                onChange={(e) => setDraft({ ...draft, target_pct: e.target.value })} /></div>
            <div><label className="label">Based on salary</label>
              <select className="input" value={draft.salary_lag_years}
                onChange={(e) => setDraft({ ...draft, salary_lag_years: e.target.value })}>
                <option value="1">Last year</option>
                <option value="2">2 years back</option>
                <option value="3">3 years back</option>
              </select></div>
            <div><label className="label">Withheld %</label>
              <input type="number" step="0.01" className="input" value={draft.withholding_pct}
                onChange={(e) => setDraft({ ...draft, withholding_pct: e.target.value })} /></div>
          </div>
          <div>
            <label className="label">Fixed amounts (gross, e.g. ramp years)</label>
            {draft.years.map((y, i) => (
              <div key={i} className="flex gap-2 mb-1">
                <input type="number" className="input w-24" placeholder="Year" value={y.year}
                  onChange={(e) => setDraft({ ...draft, years: draft.years.map((r, j) => j === i ? { ...r, year: e.target.value } : r) })} />
                <input type="number" className="input" placeholder="Gross" value={y.gross_amount}
                  onChange={(e) => setDraft({ ...draft, years: draft.years.map((r, j) => j === i ? { ...r, gross_amount: e.target.value } : r) })} />
                <button className="text-gray-400 hover:text-red-500" aria-label="Remove year"
                  onClick={() => setDraft({ ...draft, years: draft.years.filter((_, j) => j !== i) })}><Trash2 size={14} /></button>
              </div>
            ))}
            <button className="text-xs text-indigo-500 hover:underline"
              onClick={() => setDraft({ ...draft, years: [...draft.years, { year: "", gross_amount: "" }] })}>+ Add a year</button>
          </div>
          {saveMut.isError && <p className="text-xs text-red-500" role="alert">Couldn't save that plan. Check the fields and try again.</p>}
          <div className="flex gap-2">
            <button className="btn-primary text-sm" disabled={!draft.recurring_item_id || !draft.withholding_pct || saveMut.isPending}
              onClick={() => saveMut.mutate(draft)}>Save plan</button>
            <button className="btn-secondary text-sm" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="btn-secondary text-sm flex items-center gap-1" onClick={() => setDraft({ ...blank })}>
          <Plus size={14} /> Add bonus plan
        </button>
      )}

      <ConfirmDialog
        open={!!deletePlan}
        onOpenChange={(open) => !open && setDeletePlan(null)}
        icon={Trash2}
        title={`Delete the bonus plan for ${deletePlan?.item_name ?? ""}?`}
        description="Its fixed ramp amounts are removed too."
        confirmLabel="Delete"
        confirmingLabel="Deleting…"
        isPending={deleteMut.isPending}
        onConfirm={() => deletePlan && deleteMut.mutate(deletePlan.id)}
      />
    </div>
  );
}
