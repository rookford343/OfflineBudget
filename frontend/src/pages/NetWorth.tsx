import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { netWorthApi } from "../api";
import { fmt, cx } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { PlusCircle, Pencil, Trash2, Camera, HelpCircle, Loader2 } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { ConfirmDialog } from "../components/ConfirmDialog";

type Asset = { id: number; name: string; asset_type: string; current_value: string; as_of_date: string };
type Liability = { id: number; name: string; liability_type: string; current_balance: string; as_of_date: string };

const ASSET_TYPES = ["Investment Account", "Real Estate", "Vehicle", "Cash", "Cryptocurrency", "Other"];
const LIABILITY_TYPES = ["Mortgage", "Auto Loan", "Student Loan", "Personal Loan", "Other"];

function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

function chartTheme() {
  const dark = isDarkMode();
  return {
    grid: dark ? "#3a4051" : "#e5e7eb",
    tick: dark ? "#8f99a8" : "#6b7280",
  };
}

const today = new Date().toISOString().split("T")[0];
const emptyAsset = { name: "", asset_type: ASSET_TYPES[0], current_value: "", as_of_date: today };
const emptyLiability = { name: "", liability_type: LIABILITY_TYPES[0], current_balance: "", as_of_date: today };

export default function NetWorth() {
  const qc = useQueryClient();
  const balancesHidden = useBalancesHidden();
  const [showHelp, setShowHelp] = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [editingLiability, setEditingLiability] = useState<Liability | null>(null);
  const [assetForm, setAssetForm] = useState(emptyAsset);
  const [liabilityForm, setLiabilityForm] = useState(emptyLiability);
  const [showAssetForm, setShowAssetForm] = useState(false);
  const [showLiabilityForm, setShowLiabilityForm] = useState(false);
  const [deleteAsset, setDeleteAsset] = useState<Asset | null>(null);
  const [deleteLiability, setDeleteLiability] = useState<Liability | null>(null);

  const { data: totals } = useQuery({ queryKey: ["net-worth-totals"], queryFn: netWorthApi.totals });
  const { data: history = [] } = useQuery({ queryKey: ["net-worth-history"], queryFn: netWorthApi.history });
  const { data: pageAssets = [] } = useQuery<Asset[]>({ queryKey: ["net-worth-assets"], queryFn: netWorthApi.listAssets });
  const { data: pageLiabilities = [] } = useQuery<Liability[]>({ queryKey: ["net-worth-liabilities"], queryFn: netWorthApi.listLiabilities });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["net-worth-totals"] });
    qc.invalidateQueries({ queryKey: ["net-worth-assets"] });
    qc.invalidateQueries({ queryKey: ["net-worth-liabilities"] });
    qc.invalidateQueries({ queryKey: ["net-worth-history"] });
  };

  const createAssetMut = useMutation({
    mutationFn: (d: object) => netWorthApi.createAsset(d),
    onSuccess: () => { invalidate(); setShowAssetForm(false); setAssetForm(emptyAsset); },
  });
  const updateAssetMut = useMutation({
    mutationFn: ({ id, d }: { id: number; d: object }) => netWorthApi.updateAsset(id, d),
    onSuccess: () => { invalidate(); setEditingAsset(null); },
  });
  const deleteAssetMut = useMutation({ mutationFn: (id: number) => netWorthApi.removeAsset(id), onSuccess: () => { invalidate(); setDeleteAsset(null); } });

  const createLiabilityMut = useMutation({
    mutationFn: (d: object) => netWorthApi.createLiability(d),
    onSuccess: () => { invalidate(); setShowLiabilityForm(false); setLiabilityForm(emptyLiability); },
  });
  const updateLiabilityMut = useMutation({
    mutationFn: ({ id, d }: { id: number; d: object }) => netWorthApi.updateLiability(id, d),
    onSuccess: () => { invalidate(); setEditingLiability(null); },
  });
  const deleteLiabilityMut = useMutation({ mutationFn: (id: number) => netWorthApi.removeLiability(id), onSuccess: () => { invalidate(); setDeleteLiability(null); } });
  const snapshotMut = useMutation({ mutationFn: netWorthApi.snapshot, onSuccess: invalidate });
  const removeSnapshotMut = useMutation({ mutationFn: netWorthApi.removeSnapshot, onSuccess: invalidate });
  const [showHistory, setShowHistory] = useState(false);

  // Local date, not toISOString(): that returns the UTC day, so from early
  // evening onward in a western timezone it names tomorrow. The backend
  // stamps snapshots with its own local date, so the two disagreed for the
  // whole UTC-offset window each night and the button never noticed that
  // today was already captured.
  const todayIso = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  })();
  const capturedToday = (history as any[]).some((s: any) => s.snapshot_date === todayIso);

  const allChartData = (history as any[]).map((s: any) => ({
    date: s.snapshot_date,
    netWorth: parseFloat(s.net_worth),
  }));

  // Client-side only -- history is already fetched in full, so a range filter
  // here is a display concern, not a new query. Matches Securo's paired
  // range-control pattern; the granularity dimension (D/W/M/Y rollup) isn't
  // included -- that's real aggregation logic, not a display filter, and
  // wasn't worth building for a chart that's mostly daily/weekly snapshots.
  const RANGES = [
    { key: "6m", label: "6M", days: 182 },
    { key: "1y", label: "1Y", days: 365 },
    { key: "2y", label: "2Y", days: 730 },
    { key: "all", label: "All", days: null as number | null },
  ];
  const [range, setRange] = useState("1y");
  const chartData = (() => {
    const active = RANGES.find(r => r.key === range);
    if (!active || active.days == null) return allChartData;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - active.days);
    const cutoffIso = cutoff.toISOString().slice(0, 10);
    return allChartData.filter(d => d.date >= cutoffIso);
  })();

  const nw = totals?.net_worth != null ? parseFloat(totals.net_worth) : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Net Worth <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500">Assets, liabilities, and net worth over time</p>
        </div>
        <div className="text-right">
          <button
            className="btn btn-primary flex items-center gap-2"
            onClick={() => snapshotMut.mutate()}
            disabled={snapshotMut.isPending}
          >
            <Camera className="w-4 h-4" />
            {snapshotMut.isPending ? "Saving…" : capturedToday ? "Update Today's Snapshot" : "Capture Snapshot"}
          </button>
          {/* The button used to give no hint what it recorded or whether it
              had already been pressed, so it was easy to take several by
              accident and impossible to tell. */}
          <p className="text-xs text-gray-500 mt-1.5 max-w-[15rem]">
            {capturedToday
              ? "Today is already recorded. Capturing again replaces it."
              : "Records today's net worth so the chart has history."}
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Manual Assets</p>
          <p className="text-lg font-bold text-emerald-600">{totals ? maskIfHidden(balancesHidden, fmt(parseFloat(totals.total_assets))) : "—"}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Account Balances</p>
          <p className="text-lg font-bold text-emerald-600">{totals ? maskIfHidden(balancesHidden, fmt(parseFloat(totals.account_balances))) : "—"}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Liabilities</p>
          <p className="text-lg font-bold text-red-500">
            {totals ? maskIfHidden(balancesHidden, fmt(parseFloat(totals.card_balances) + parseFloat(totals.total_liabilities))) : "—"}
          </p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Net Worth</p>
          <p className={`text-2xl font-bold ${nw != null && nw >= 0 ? "text-emerald-600" : "text-red-500"}`}>
            {nw != null ? maskIfHidden(balancesHidden, fmt(nw)) : "—"}
          </p>
        </div>
      </div>

      {/* Trend Chart */}
      {allChartData.length > 0 ? (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900">Net Worth Over Time</h3>
            <div className="flex gap-1 bg-gray-100 dark:bg-gray-700/50 rounded-lg p-0.5">
              {RANGES.map(r => (
                <button
                  key={r.key}
                  onClick={() => setRange(r.key)}
                  className={cx(
                    "px-2.5 py-1 text-xs font-medium rounded-md",
                    range === r.key
                      ? "bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-300 shadow-sm"
                      : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                  )}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="netWorthGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={nw != null && nw >= 0 ? "#6366f1" : "#ef4444"} stopOpacity={0.18} />
                  <stop offset="95%" stopColor={nw != null && nw >= 0 ? "#6366f1" : "#ef4444"} stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={chartTheme().grid} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => fmt(v)} />
              <Area type="monotone" dataKey="netWorth" stroke={nw != null && nw >= 0 ? "#6366f1" : "#ef4444"} strokeWidth={2} fill="url(#netWorthGradient)" dot={{ r: 3 }} animationDuration={700} animationEasing="ease-out" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="card text-center py-6 text-gray-400 text-sm">
          No snapshots yet. "Capture Snapshot" records today's figures so this chart has something to plot.
        </div>
      )}

      {(history as any[]).length > 0 && (
        <div className="card">
          <button
            className="flex items-center justify-between w-full"
            onClick={() => setShowHistory(v => !v)}
          >
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">
              Snapshot History
              <span className="ml-2 text-xs font-normal text-gray-500">{(history as any[]).length}</span>
            </h3>
            <span className="text-xs text-gray-500">{showHistory ? "Hide" : "Show"}</span>
          </button>
          {showHistory && (
            <div className="mt-3 divide-y divide-gray-50 dark:divide-gray-800">
              {[...(history as any[])].reverse().map((s: any) => (
                <div key={s.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-gray-600 dark:text-gray-300">
                    {new Date(s.snapshot_date + "T12:00:00").toLocaleDateString("en-US",
                      { month: "short", day: "numeric", year: "numeric" })}
                    {s.snapshot_date === todayIso && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-indigo-500">today</span>
                    )}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className={`tabular-nums font-medium ${parseFloat(s.net_worth) >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                      {fmt(parseFloat(s.net_worth))}
                    </span>
                    <button
                      onClick={() => removeSnapshotMut.mutate(s.id)}
                      disabled={removeSnapshotMut.isPending}
                      className="text-gray-300 hover:text-red-500 disabled:opacity-50"
                      title="Delete this snapshot"
                      aria-label="Delete this snapshot">
                      {removeSnapshotMut.isPending && removeSnapshotMut.variables === s.id
                        ? <Loader2 size={14} className="animate-spin" />
                        : <Trash2 size={14} />}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Assets */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Assets</h3>
          <button
            className="btn btn-sm btn-secondary flex items-center gap-1"
            onClick={() => { setShowAssetForm(true); setEditingAsset(null); setAssetForm(emptyAsset); }}
          >
            <PlusCircle className="w-4 h-4" /> Add Asset
          </button>
        </div>

        {(showAssetForm || editingAsset) && (
          <div className="bg-gray-50 rounded-lg p-4 mb-4 grid grid-cols-2 gap-3">
            <input className="input col-span-2" placeholder="Name"
              value={editingAsset ? editingAsset.name : assetForm.name}
              onChange={e => editingAsset ? setEditingAsset({ ...editingAsset, name: e.target.value }) : setAssetForm({ ...assetForm, name: e.target.value })} />
            <select className="input"
              value={editingAsset ? editingAsset.asset_type : assetForm.asset_type}
              onChange={e => editingAsset ? setEditingAsset({ ...editingAsset, asset_type: e.target.value }) : setAssetForm({ ...assetForm, asset_type: e.target.value })}>
              {ASSET_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <input className="input" type="number" step="0.01" placeholder="Current Value"
              value={editingAsset ? editingAsset.current_value : assetForm.current_value}
              onChange={e => editingAsset ? setEditingAsset({ ...editingAsset, current_value: e.target.value }) : setAssetForm({ ...assetForm, current_value: e.target.value })} />
            <input className="input" type="date"
              value={editingAsset ? editingAsset.as_of_date : assetForm.as_of_date}
              onChange={e => editingAsset ? setEditingAsset({ ...editingAsset, as_of_date: e.target.value }) : setAssetForm({ ...assetForm, as_of_date: e.target.value })} />
            <div className="flex gap-2">
              <button className="btn btn-primary" onClick={() => {
                if (editingAsset) {
                  updateAssetMut.mutate({ id: editingAsset.id, d: { name: editingAsset.name, asset_type: editingAsset.asset_type, current_value: parseFloat(editingAsset.current_value), as_of_date: editingAsset.as_of_date } });
                } else {
                  createAssetMut.mutate({ ...assetForm, current_value: parseFloat(assetForm.current_value) });
                }
              }}>Save</button>
              <button className="btn btn-secondary" onClick={() => { setEditingAsset(null); setShowAssetForm(false); }}>Cancel</button>
            </div>
          </div>
        )}

        {pageAssets.length === 0 && !showAssetForm && (
          <p className="text-sm text-gray-400 text-center py-4">No assets yet.</p>
        )}
        <div className="space-y-2">
          {pageAssets.map((a) => (
            <div key={a.id} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
              <div>
                <span className="font-medium text-gray-900">{a.name}</span>
                <span className="ml-2 text-xs text-gray-400">{a.asset_type}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="font-semibold text-emerald-600">{maskIfHidden(balancesHidden, fmt(parseFloat(a.current_value)))}</span>
                <button onClick={() => { setEditingAsset(a); setShowAssetForm(false); }} className="text-gray-400 hover:text-indigo-600"><Pencil className="w-4 h-4" /></button>
                <button onClick={() => setDeleteAsset(a)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Liabilities */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Liabilities</h3>
          <button
            className="btn btn-sm btn-secondary flex items-center gap-1"
            onClick={() => { setShowLiabilityForm(true); setEditingLiability(null); setLiabilityForm(emptyLiability); }}
          >
            <PlusCircle className="w-4 h-4" /> Add Liability
          </button>
        </div>

        {(showLiabilityForm || editingLiability) && (
          <div className="bg-gray-50 rounded-lg p-4 mb-4 grid grid-cols-2 gap-3">
            <input className="input col-span-2" placeholder="Name"
              value={editingLiability ? editingLiability.name : liabilityForm.name}
              onChange={e => editingLiability ? setEditingLiability({ ...editingLiability, name: e.target.value }) : setLiabilityForm({ ...liabilityForm, name: e.target.value })} />
            <select className="input"
              value={editingLiability ? editingLiability.liability_type : liabilityForm.liability_type}
              onChange={e => editingLiability ? setEditingLiability({ ...editingLiability, liability_type: e.target.value }) : setLiabilityForm({ ...liabilityForm, liability_type: e.target.value })}>
              {LIABILITY_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <input className="input" type="number" step="0.01" placeholder="Current Balance"
              value={editingLiability ? editingLiability.current_balance : liabilityForm.current_balance}
              onChange={e => editingLiability ? setEditingLiability({ ...editingLiability, current_balance: e.target.value }) : setLiabilityForm({ ...liabilityForm, current_balance: e.target.value })} />
            <input className="input" type="date"
              value={editingLiability ? editingLiability.as_of_date : liabilityForm.as_of_date}
              onChange={e => editingLiability ? setEditingLiability({ ...editingLiability, as_of_date: e.target.value }) : setLiabilityForm({ ...liabilityForm, as_of_date: e.target.value })} />
            <div className="flex gap-2">
              <button className="btn btn-primary" onClick={() => {
                if (editingLiability) {
                  updateLiabilityMut.mutate({ id: editingLiability.id, d: { name: editingLiability.name, liability_type: editingLiability.liability_type, current_balance: parseFloat(editingLiability.current_balance), as_of_date: editingLiability.as_of_date } });
                } else {
                  createLiabilityMut.mutate({ ...liabilityForm, current_balance: parseFloat(liabilityForm.current_balance) });
                }
              }}>Save</button>
              <button className="btn btn-secondary" onClick={() => { setEditingLiability(null); setShowLiabilityForm(false); }}>Cancel</button>
            </div>
          </div>
        )}

        {pageLiabilities.length === 0 && !showLiabilityForm && (
          <p className="text-sm text-gray-400 text-center py-4">No liabilities yet.</p>
        )}
        <div className="space-y-2">
          {pageLiabilities.map((l) => (
            <div key={l.id} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
              <div>
                <span className="font-medium text-gray-900">{l.name}</span>
                <span className="ml-2 text-xs text-gray-400">{l.liability_type}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="font-semibold text-red-500">{maskIfHidden(balancesHidden, fmt(parseFloat(l.current_balance)))}</span>
                <button onClick={() => { setEditingLiability(l); setShowLiabilityForm(false); }} className="text-gray-400 hover:text-indigo-600"><Pencil className="w-4 h-4" /></button>
                <button onClick={() => setDeleteLiability(l)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
          ))}
        </div>
      </div>
      {showHelp && <HelpPanel title="Net Worth" body={"Your net worth = assets + account balances − credit card balances − liabilities.\n\nAdd manual assets (investments, real estate, vehicles) and liabilities (mortgage, loans). Those figures are what the app knows right now — editing them changes the current total but not any past snapshot.\n\nA snapshot freezes today's total so the chart has a point to plot. Nothing is recorded automatically, so the trend line only has the dates you captured.\n\nCapturing twice on the same day replaces that day rather than adding a second point, and any snapshot can be deleted from Snapshot History if it was taken with wrong figures."} onClose={() => setShowHelp(false)} />}
      <ConfirmDialog
        open={!!deleteAsset}
        onOpenChange={(open) => !open && setDeleteAsset(null)}
        icon={Trash2}
        title="Delete this asset?"
        description={`"${deleteAsset?.name}" will be permanently removed from your net worth.`}
        confirmLabel="Delete"
        confirmingLabel="Deleting…"
        isPending={deleteAssetMut.isPending}
        onConfirm={() => deleteAssetMut.mutate(deleteAsset!.id)}
      />
      <ConfirmDialog
        open={!!deleteLiability}
        onOpenChange={(open) => !open && setDeleteLiability(null)}
        icon={Trash2}
        title="Delete this liability?"
        description={`"${deleteLiability?.name}" will be permanently removed from your net worth.`}
        confirmLabel="Delete"
        confirmingLabel="Deleting…"
        isPending={deleteLiabilityMut.isPending}
        onConfirm={() => deleteLiabilityMut.mutate(deleteLiability!.id)}
      />
    </div>
  );
}
