import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { recurringApi, categoriesApi } from "../api";
import { fmt } from "../lib/utils";
import { CategoryOptions } from "../lib/selectOptions";
import { Inbox, Check, X, Copy } from "lucide-react";

/**
 * "Needs a home": recurring charges with no category, repeating charges
 * nobody is tracking yet, and probable duplicates. Each answer also teaches
 * a merchant rule server-side, so the same charge never lands here twice.
 */

// Hoisted to module scope (deviation from the brief's inline definition):
// a component declared inside another component's render body gets a new
// identity every render, so React unmounts and remounts the <select> on every
// keystroke/pick elsewhere in the parent, dropping focus and open dropdowns.
function CategoryPicker(
  { value, onChange, categories }: { value: string; onChange: (v: string) => void; categories: any[] },
) {
  return (
    <select
      className="input text-sm w-48"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Choose a category…</option>
      <CategoryOptions categories={categories} type="expense" />
    </select>
  );
}

export default function TriageInbox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["recurring-triage"], queryFn: recurringApi.triage });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(true);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["recurring-triage"] });
    qc.invalidateQueries({ queryKey: ["recurring"] });
    qc.invalidateQueries({ queryKey: ["left-to-budget"] });
  };
  const classify = useMutation({ mutationFn: recurringApi.triageClassify, onSuccess: refresh });
  const dismiss = useMutation({ mutationFn: recurringApi.triageDismiss, onSuccess: refresh });
  const duplicate = useMutation({
    mutationFn: ({ keep, drop }: { keep: number; drop: number }) => recurringApi.triageDuplicate(keep, drop),
    onSuccess: refresh,
  });

  if (!data) return null;
  const total = data.uncategorized.length + data.untracked.length + data.duplicates.length;
  if (total === 0) return null;

  const pickFor = (key: string, guess: number | null) => picks[key] ?? (guess ? String(guess) : "");
  const setPick = (key: string, value: string) => setPicks((p) => ({ ...p, [key]: value }));

  return (
    <div className="card border-amber-200 dark:border-amber-800">
      <button className="flex w-full items-center justify-between" onClick={() => setOpen(!open)}>
        <span className="flex items-center gap-2 font-semibold text-gray-800 dark:text-gray-100">
          <Inbox size={18} className="text-amber-500" /> Needs a home
        </span>
        <span className="text-sm text-amber-600 dark:text-amber-400">
          {data.unclassified_count} unclassified · {fmt(data.unclassified_monthly_total)}/mo
        </span>
      </button>

      {open && (
        <div className="mt-3 divide-y divide-gray-100 dark:divide-gray-700">
          {data.uncategorized.map((u: any) => {
            const key = `item:${u.recurring_item_id}`;
            const chosen = pickFor(key, u.guess_category_id);
            return (
              <div key={key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <p className="text-sm font-medium">{u.name}</p>
                  <p className="text-xs text-gray-400">
                    {fmt(u.amount)} {u.frequency}
                    {u.guess_category_name && <> · best guess: {u.guess_category_name}</>}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <CategoryPicker value={chosen} onChange={(v) => setPick(key, v)} categories={categories} />
                  <button
                    className="btn-primary text-xs px-2 py-1"
                    disabled={!chosen || classify.isPending}
                    onClick={() => classify.mutate({ recurring_item_id: u.recurring_item_id, category_id: Number(chosen) })}
                  >
                    <Check size={14} />
                  </button>
                </div>
              </div>
            );
          })}

          {data.untracked.map((s: any) => {
            const key = `pattern:${s.pattern_key}`;
            const chosen = pickFor(key, s.guess_category_id);
            return (
              <div key={key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <p className="text-sm font-medium">{s.description}</p>
                  <p className="text-xs text-gray-400">
                    Repeats {s.frequency} · {fmt(s.median_amount)} · seen {s.occurrences}×
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <CategoryPicker value={chosen} onChange={(v) => setPick(key, v)} categories={categories} />
                  <button
                    className="btn-primary text-xs px-2 py-1"
                    disabled={!chosen || classify.isPending}
                    onClick={() => classify.mutate({ pattern_key: s.pattern_key, category_id: Number(chosen) })}
                  >
                    <Check size={14} />
                  </button>
                  <button className="btn-secondary py-1 px-2 text-xs" onClick={() => dismiss.mutate(s.pattern_key)}>
                    Not recurring
                  </button>
                </div>
              </div>
            );
          })}

          {data.duplicates.map((d: any) => (
            <div key={d.pair_key} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <p className="flex items-center gap-2 text-sm">
                <Copy size={14} className="text-gray-400" />
                <span className="font-medium">{d.a.name}</span> and <span className="font-medium">{d.b.name}</span>
                <span className="text-xs text-gray-400">look like the same bill</span>
              </p>
              <div className="flex items-center gap-2">
                <button className="btn-secondary py-1 px-2 text-xs"
                  onClick={() => duplicate.mutate({ keep: d.a.recurring_item_id, drop: d.b.recurring_item_id })}>
                  Keep {d.a.name}
                </button>
                <button className="btn-secondary py-1 px-2 text-xs"
                  onClick={() => duplicate.mutate({ keep: d.b.recurring_item_id, drop: d.a.recurring_item_id })}>
                  Keep {d.b.name}
                </button>
                <button className="btn-ghost p-1" title="Not a duplicate" onClick={() => dismiss.mutate(d.pair_key)}>
                  <X size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
