import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { authApi, bankSyncApi } from "../../api";
import { getTheme, setTheme } from "../../store/theme";
import { isParallelOpsEnabled, setParallelOpsEnabled } from "../../store/parallelOps";
import { Moon, Sun, Wand2, Flag, Bug, Clock } from "lucide-react";
import { PINNABLE_ITEMS, loadPinnedNav, PINNED_STORAGE_KEY } from "../../lib/navItems";
import { parseServerDateTime } from "../../lib/utils";

export default function PreferencesTab() {
  const [dark, setDark] = useState(getTheme() === "dark");
  function toggleDark() { const next = !dark; setDark(next); setTheme(next); }

  const [parallelOps, setParallelOpsState] = useState(isParallelOpsEnabled());
  function toggleParallelOps() {
    const next = !parallelOps;
    setParallelOpsState(next);
    setParallelOpsEnabled(next);
  }

  // Seeded from the server so the displayed value matches the current
  // setting on load, same as the original Settings.tsx's shared `me` effect.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [transferIncrement, setTransferIncrement] = useState("");
  useEffect(() => { if (me) setTransferIncrement(me.transfer_increment ?? "1000"); }, [me]);
  const [savingsStrategy, setSavingsStrategy] = useState("save_monthly");
  useEffect(() => { if (me) setSavingsStrategy(me.savings_strategy ?? "save_monthly"); }, [me]);
  const taxMut = useMutation({ mutationFn: authApi.updateMe });

  const debugRawBankData = !!me?.debug_capture_raw_bank_data;
  function toggleDebugRawBankData() {
    taxMut.mutate({ debug_capture_raw_bank_data: !debugRawBankData });
  }

  const { data: schedulerRuns = [] } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: bankSyncApi.schedulerStatus,
    refetchInterval: 60_000,
  });
  const JOB_LABELS: Record<string, string> = { bank_sync: "Bank Sync", daily_summary: "Daily Summary Email" };
  function relativeTime(iso: string | null) {
    if (!iso) return "never";
    const diffMs = Date.now() - parseServerDateTime(iso).getTime();
    const hrs = diffMs / 3_600_000;
    if (hrs < 1) return `${Math.max(1, Math.round(diffMs / 60_000))}m ago`;
    if (hrs < 48) return `${Math.round(hrs)}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  }

  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);
  function togglePin(to: string) {
    const next = pinned.includes(to) ? pinned.filter(t => t !== to) : [...pinned, to];
    setPinned(next);
    localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("nav-order-changed"));
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Preferences</h3>
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-3">
          {dark ? <Moon size={16} className="text-indigo-400" /> : <Sun size={16} className="text-amber-500" />}
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Dark Mode</span>
        </div>
        <button
          onClick={toggleDark}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${dark ? "bg-indigo-600" : "bg-gray-200"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${dark ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>
      <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Flag size={16} className="text-red-400" />
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Parallel Ops</span>
            <p className="text-xs text-gray-400">Show a flag icon on Forecast, Transactions, and Household Snapshot to report numbers that look wrong</p>
          </div>
        </div>
        <button
          onClick={toggleParallelOps}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${parallelOps ? "bg-indigo-600" : "bg-gray-200"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${parallelOps ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>
      <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Wand2 size={16} className="text-indigo-400" />
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Setup Wizard</span>
            <p className="text-xs text-gray-400">Add an account and income recurring item</p>
          </div>
        </div>
        <button
          onClick={() => window.dispatchEvent(new Event("open-wizard"))}
          className="btn-secondary text-sm px-3 py-1.5"
        >
          Open
        </button>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="mb-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Pinned Sidebar Items</span>
          <p className="text-xs text-gray-400">Dashboard is always pinned. Choose a few more for quick access above the grouped sections.</p>
        </div>
        <div className="space-y-1">
          {PINNABLE_ITEMS.map(item => (
            <label key={item.to} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 rounded accent-indigo-600"
                checked={pinned.includes(item.to)}
                onChange={() => togglePin(item.to)}
              />
              <item.icon size={14} className="text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">{item.label}</span>
            </label>
          ))}
        </div>
      </div>
      {/* Whether the monthly savings transfer is a commitment. It changes
          Left to Spend directly, so the consequence is spelled out rather
          than left to be discovered. */}
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Savings Strategy</span>
            <p className="text-xs text-gray-400">
              {savingsStrategy === "pull_from_savings"
                ? "Not saving monthly — the savings budget stays spendable, so Left to Spend is higher by it."
                : "Saving each month — the savings budget leaves the spendable pool."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="input w-48 text-sm"
              value={savingsStrategy}
              onChange={(e) => { setSavingsStrategy(e.target.value); taxMut.mutate({ savings_strategy: e.target.value }); }}
            >
              <option value="save_monthly">Save each month</option>
              <option value="pull_from_savings">Pull from savings</option>
            </select>
          </div>
        </div>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Suggested Transfer Increment</span>
            <p className="text-xs text-gray-400">Suggested transfers round up to this amount (e.g. $1,000 steps)</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              step="1"
              className="input w-28 text-sm text-right"
              value={transferIncrement}
              onChange={(e) => setTransferIncrement(e.target.value)}
            />
            <button
              onClick={() => taxMut.mutate({ transfer_increment: transferIncrement ? parseFloat(transferIncrement) : null })}
              disabled={taxMut.isPending}
              className="btn-secondary text-xs px-3 py-1.5"
            >
              {taxMut.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-2 mb-2">
          <Clock size={16} className="text-gray-400" />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Background Jobs</span>
        </div>
        <p className="text-xs text-gray-400 mb-2">
          Bank sync and the daily email run on a schedule, and self-retry if the Mac was asleep or offline when they were due.
        </p>
        <div className="space-y-1.5">
          {(schedulerRuns as any[]).length === 0 && (
            <p className="text-xs text-gray-400 italic">No runs recorded yet.</p>
          )}
          {(schedulerRuns as any[]).map((run: any) => (
            <div key={run.job_name} className="flex items-center justify-between text-xs py-1">
              <span className="text-gray-600 dark:text-gray-300">{JOB_LABELS[run.job_name] ?? run.job_name}</span>
              <span className={run.last_error ? "text-red-600 dark:text-red-400" : "text-gray-500 dark:text-gray-400"}>
                {run.last_error
                  ? `failed ${relativeTime(run.last_attempt_at)}: ${run.last_error}`
                  : `last succeeded ${relativeTime(run.last_success_at)}`}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Bug size={16} className="text-amber-500" />
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Capture Raw Bank Data (debug)</span>
            <p className="text-xs text-gray-400">Save the full unmapped bank-sync record per transaction so you can inspect what fields the bank actually sends. Off by default — turn on only while debugging, then back off.</p>
          </div>
        </div>
        <button
          onClick={toggleDebugRawBankData}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors shrink-0 ${debugRawBankData ? "bg-amber-500" : "bg-gray-200"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${debugRawBankData ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>
    </div>
  );
}
