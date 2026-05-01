import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { goalsApi, accountsApi } from "../api";
import { fmt } from "../lib/utils";
import { Plus, Pencil, Trash2, Target } from "lucide-react";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function projectedCompletion(months_remaining: number | null): string {
  if (months_remaining == null) return "";
  const d = new Date();
  d.setMonth(d.getMonth() + months_remaining);
  return `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
}

interface GoalFormData {
  name: string;
  target_amount: string;
  current_amount: string;
  target_date: string;
  linked_account_id: string;
  notes: string;
}

const EMPTY_FORM: GoalFormData = {
  name: "",
  target_amount: "",
  current_amount: "0",
  target_date: "",
  linked_account_id: "",
  notes: "",
};

export default function Goals() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<GoalFormData>(EMPTY_FORM);

  const { data: goals = [], isLoading } = useQuery<any[]>({
    queryKey: ["goals"],
    queryFn: goalsApi.list,
  });

  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
  });

  const createMutation = useMutation({
    mutationFn: (data: object) => goalsApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); resetForm(); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => goalsApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); resetForm(); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => goalsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });

  function resetForm() {
    setForm(EMPTY_FORM);
    setShowForm(false);
    setEditing(null);
  }

  function startEdit(goal: any) {
    setEditing(goal);
    setForm({
      name: goal.name,
      target_amount: String(goal.target_amount),
      current_amount: String(goal.current_amount),
      target_date: goal.target_date ?? "",
      linked_account_id: goal.linked_account_id ? String(goal.linked_account_id) : "",
      notes: goal.notes ?? "",
    });
    setShowForm(true);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const payload: any = {
      name: form.name,
      target_amount: parseFloat(form.target_amount),
      current_amount: parseFloat(form.current_amount || "0"),
      target_date: form.target_date || null,
      linked_account_id: form.linked_account_id ? parseInt(form.linked_account_id) : null,
      notes: form.notes || null,
    };
    if (editing) {
      updateMutation.mutate({ id: editing.id, data: payload });
    } else {
      createMutation.mutate(payload);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Savings Goals</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">Track progress toward your financial targets</p>
        </div>
        <button
          onClick={() => { setEditing(null); setForm(EMPTY_FORM); setShowForm(true); }}
          className="btn-primary flex items-center gap-2"
        >
          <Plus size={16} /> New Goal
        </button>
      </div>

      {/* Form */}
      {showForm && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-4">
            {editing ? "Edit Goal" : "New Savings Goal"}
          </h3>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="label">Goal Name</label>
                <input
                  type="text"
                  className="input w-full"
                  placeholder="Emergency Fund"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="label">Target Amount</label>
                <input
                  type="number"
                  className="input w-full"
                  placeholder="10000"
                  step="0.01"
                  min="0"
                  value={form.target_amount}
                  onChange={e => setForm(f => ({ ...f, target_amount: e.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="label">Current Amount</label>
                <input
                  type="number"
                  className="input w-full"
                  placeholder="0"
                  step="0.01"
                  min="0"
                  value={form.current_amount}
                  onChange={e => setForm(f => ({ ...f, current_amount: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Target Date (optional)</label>
                <input
                  type="date"
                  className="input w-full"
                  value={form.target_date}
                  onChange={e => setForm(f => ({ ...f, target_date: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Linked Account (optional)</label>
                <select
                  className="input w-full"
                  value={form.linked_account_id}
                  onChange={e => setForm(f => ({ ...f, linked_account_id: e.target.value }))}
                >
                  <option value="">None</option>
                  {accounts.map((a: any) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Notes (optional)</label>
                <input
                  type="text"
                  className="input w-full"
                  placeholder="Additional notes"
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                />
              </div>
            </div>
            <div className="flex gap-3 pt-2">
              <button type="submit" className="btn-primary">
                {editing ? "Save Changes" : "Create Goal"}
              </button>
              <button type="button" onClick={resetForm} className="btn-secondary">Cancel</button>
            </div>
          </form>
        </div>
      )}

      {/* Goals grid */}
      {isLoading ? (
        <div className="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">Loading goals…</div>
      ) : goals.length === 0 ? (
        <div className="card text-center py-12">
          <Target className="mx-auto text-indigo-300 dark:text-indigo-700 mb-3" size={40} />
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-1">No savings goals yet</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Create your first goal to start tracking your progress.</p>
          <button onClick={() => setShowForm(true)} className="btn-primary">Create First Goal</button>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {goals.map((goal: any) => {
            const pct = Math.min(parseFloat(goal.percent_complete), 100);
            const isComplete = pct >= 100;
            return (
              <div key={goal.id} className="card space-y-3">
                <div className="flex items-start justify-between">
                  <h3 className="font-semibold text-gray-900 dark:text-white leading-tight">{goal.name}</h3>
                  <div className="flex gap-1 shrink-0 ml-2">
                    <button onClick={() => startEdit(goal)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 dark:text-gray-500">
                      <Pencil size={14} />
                    </button>
                    <button onClick={() => deleteMutation.mutate(goal.id)} className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-400 dark:text-gray-500 hover:text-red-500">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {/* Progress bar */}
                <div>
                  <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
                    <span>{pct.toFixed(1)}% complete</span>
                    <span>{isComplete ? "✓ Reached!" : `${fmt(parseFloat(goal.current_amount))} of ${fmt(parseFloat(goal.target_amount))}`}</span>
                  </div>
                  <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-2 rounded-full transition-all ${isComplete ? "bg-blue-500" : "bg-emerald-500"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>

                {/* Stats */}
                <div className="space-y-1 text-sm">
                  {goal.target_date && (
                    <div className="flex justify-between text-gray-600 dark:text-gray-400">
                      <span>Target date</span>
                      <span className="font-medium text-gray-900 dark:text-white">
                        {new Date(goal.target_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                      </span>
                    </div>
                  )}
                  {goal.monthly_needed != null && !isComplete && (
                    <div className="flex justify-between text-gray-600 dark:text-gray-400">
                      <span>Needed per month</span>
                      <span className="font-medium text-indigo-600 dark:text-indigo-400">{fmt(parseFloat(goal.monthly_needed))}</span>
                    </div>
                  )}
                  {goal.months_remaining != null && !isComplete && (
                    <div className="flex justify-between text-gray-600 dark:text-gray-400">
                      <span>Projected completion</span>
                      <span className="font-medium text-gray-900 dark:text-white">{projectedCompletion(goal.months_remaining)}</span>
                    </div>
                  )}
                  {goal.notes && (
                    <p className="text-xs text-gray-400 dark:text-gray-500 pt-1">{goal.notes}</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
