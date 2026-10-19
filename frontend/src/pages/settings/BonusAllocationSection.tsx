import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, bonusPlansApi } from "../../api";
import { fmt, fmtDate } from "../../lib/utils";
import { AccountOptions } from "../../lib/selectOptions";
import { describeSplit, splitBonus, type AllocationStep, type AllocationStepKind } from "../../lib/bonusSplit";
import { ChevronUp, ChevronDown, Plus, Trash2 } from "lucide-react";

type StepDraft = {
  account_id: string;
  kind: AllocationStepKind;
  value: string;
  round_to: string;
};

const blankStep: StepDraft = { account_id: "", kind: "fixed", value: "", round_to: "" };

const KIND_LABELS: Record<AllocationStepKind, string> = {
  fixed: "Fixed $",
  percent: "% of bonus",
  rest: "The rest",
};

/** "When a bonus lands": an ordered list of steps that move part of each
 *  bonus from checking to savings accounts on the payout day, plus a
 *  shortfall account for when the bonus can't cover the fixed amounts.
 *  Rendered at the end of BonusPlansSection -- see
 *  backend/services/bonus_allocation.py for the server-side waterfall this
 *  mirrors for the preview line below. */
export default function BonusAllocationSection() {
  const qc = useQueryClient();
  const { data: allocation } = useQuery<any>({ queryKey: ["bonus-allocation"], queryFn: bonusPlansApi.getAllocation });
  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: plans = [] } = useQuery<any[]>({ queryKey: ["bonus-plans"], queryFn: bonusPlansApi.list });

  const [steps, setSteps] = useState<StepDraft[]>([]);
  const [shortfallAccountId, setShortfallAccountId] = useState("");
  const [shortfallRoundTo, setShortfallRoundTo] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (allocation) {
      setSteps(
        allocation.steps.map((s: any) => ({
          account_id: String(s.account_id),
          kind: s.kind,
          value: s.value ?? "",
          round_to: s.round_to ?? "",
        })),
      );
      setShortfallAccountId(allocation.shortfall_account_id != null ? String(allocation.shortfall_account_id) : "");
      setShortfallRoundTo(allocation.shortfall_round_to ?? "");
    }
  }, [allocation]);

  const saveMut = useMutation({
    mutationFn: () =>
      bonusPlansApi.putAllocation({
        steps: steps.map((s) => ({
          account_id: parseInt(s.account_id),
          kind: s.kind,
          value: s.kind === "rest" ? null : s.value || null,
          round_to: s.round_to || null,
        })),
        shortfall_account_id: shortfallAccountId ? parseInt(shortfallAccountId) : null,
        shortfall_round_to: shortfallRoundTo || null,
      }),
    onSuccess: () => {
      ["bonus-allocation", "forecast-quarters", "forecast-multi-year", "forecast-risk", "budget-snapshot"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] }),
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const hasRestElsewhere = (idx: number) => steps.some((s, i) => i !== idx && s.kind === "rest");

  const updateStep = (idx: number, patch: Partial<StepDraft>) =>
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));

  const changeKind = (idx: number, kind: AllocationStepKind) =>
    setSteps((prev) => {
      const next = prev.map((s, i) => (i === idx ? { ...s, kind, value: kind === "rest" ? "" : s.value } : s));
      if (kind === "rest") {
        // A rest step always stays last -- move it there now rather than
        // only rejecting it on save.
        const [row] = next.splice(idx, 1);
        next.push(row);
      }
      return next;
    });

  const addStep = () =>
    setSteps((prev) => {
      const restIdx = prev.findIndex((s) => s.kind === "rest");
      if (restIdx === -1) return [...prev, { ...blankStep }];
      const next = [...prev];
      next.splice(restIdx, 0, { ...blankStep });
      return next;
    });

  const removeStep = (idx: number) => setSteps((prev) => prev.filter((_, i) => i !== idx));

  const moveUp = (idx: number) =>
    setSteps((prev) => {
      if (idx <= 0) return prev;
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      return next;
    });

  const moveDown = (idx: number) =>
    setSteps((prev) => {
      if (idx >= prev.length - 1) return prev;
      const next = [...prev];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return next;
    });

  const preview = useMemo(() => {
    const upcoming = plans.map((p: any) => p.upcoming?.[0]).filter((u: any) => u && u.net != null);
    if (upcoming.length === 0) return null;
    const total = upcoming.reduce((sum: number, u: any) => sum + Number(u.net), 0);
    const date = [...upcoming.map((u: any) => u.date)].sort()[0];
    const liveSteps: AllocationStep[] = steps
      .filter((s) => s.account_id)
      .map((s) => ({
        account_id: parseInt(s.account_id),
        kind: s.kind,
        value: s.kind === "rest" ? null : s.value || null,
        round_to: s.round_to || null,
      }));
    const shortfallId = shortfallAccountId ? parseInt(shortfallAccountId) : null;
    const legs = splitBonus(total, liveSteps, shortfallId, shortfallRoundTo || null);
    const nameOf = (id: number) => accounts.find((a: any) => a.id === id)?.name ?? "that account";
    return { date, text: describeSplit(total, legs, nameOf, fmt) };
  }, [plans, steps, shortfallAccountId, shortfallRoundTo, accounts]);

  return (
    <div className="space-y-3 pt-6 mt-6 border-t border-gray-100 dark:border-gray-800">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">When a bonus lands</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Move part of each bonus from checking to savings accounts on the payout day. For example: "$25,000 to Money
        Market, the rest to Savings rounded down to $1,000. Anything left stays in checking."
      </p>

      <div className="space-y-2 max-w-2xl">
        {steps.map((step, idx) => {
          const isRest = step.kind === "rest";
          const nextIsRest = steps[idx + 1]?.kind === "rest";
          return (
            <div key={idx} className="flex flex-wrap items-center gap-2">
              <select
                className="input flex-1 min-w-[10rem]"
                value={step.account_id}
                onChange={(e) => updateStep(idx, { account_id: e.target.value })}
              >
                <option value="">Choose an account…</option>
                <AccountOptions accounts={accounts} />
              </select>
              <select
                className="input w-32"
                value={step.kind}
                onChange={(e) => changeKind(idx, e.target.value as AllocationStepKind)}
              >
                <option value="fixed">{KIND_LABELS.fixed}</option>
                <option value="percent">{KIND_LABELS.percent}</option>
                {(!hasRestElsewhere(idx) || isRest) && <option value="rest">{KIND_LABELS.rest}</option>}
              </select>
              {!isRest && (
                <input
                  type="number"
                  className="input w-28"
                  placeholder={step.kind === "percent" ? "%" : "$"}
                  value={step.value}
                  onChange={(e) => updateStep(idx, { value: e.target.value })}
                />
              )}
              <input
                type="number"
                className="input w-32"
                placeholder="Round down to $"
                value={step.round_to}
                onChange={(e) => updateStep(idx, { round_to: e.target.value })}
              />
              <button
                className="text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:hover:text-gray-400"
                aria-label="Move step up"
                disabled={idx === 0 || isRest}
                onClick={() => moveUp(idx)}
              >
                <ChevronUp size={16} />
              </button>
              <button
                className="text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:hover:text-gray-400"
                aria-label="Move step down"
                disabled={idx === steps.length - 1 || isRest || nextIsRest}
                onClick={() => moveDown(idx)}
              >
                <ChevronDown size={16} />
              </button>
              <button className="text-gray-400 hover:text-red-500" aria-label="Remove step" onClick={() => removeStep(idx)}>
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
        <button className="text-xs text-indigo-500 hover:underline flex items-center gap-1" onClick={addStep}>
          <Plus size={14} /> Add step
        </button>
      </div>

      <div className="max-w-2xl">
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
          If the bonus can't cover the fixed amounts, send all of it to …
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input flex-1 min-w-[10rem]"
            value={shortfallAccountId}
            onChange={(e) => setShortfallAccountId(e.target.value)}
          >
            <option value="">None</option>
            <AccountOptions accounts={accounts} />
          </select>
          <input
            type="number"
            className="input w-32"
            placeholder="Round down to $"
            value={shortfallRoundTo}
            onChange={(e) => setShortfallRoundTo(e.target.value)}
          />
        </div>
      </div>

      {preview && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Next bonus ({fmtDate(preview.date)}): {preview.text}
        </p>
      )}

      {saveMut.isError && (
        <p className="text-xs text-red-500" role="alert">
          Couldn't save. Check that each step has an account and a valid amount, and that 'the rest' is last.
        </p>
      )}

      <div className="flex items-center gap-3">
        <button className="btn-secondary text-sm" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
          Save
        </button>
        {saved && <span className="text-sm text-green-600">Saved!</span>}
      </div>
    </div>
  );
}
