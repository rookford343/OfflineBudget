import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { netWorthApi } from "../api";
import { fmt } from "../lib/utils";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { PlusCircle, Pencil, Trash2, Camera, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

type Asset = { id: number; name: string; asset_type: string; current_value: string; as_of_date: string };
type Liability = { id: number; name: string; liability_type: string; current_balance: string; as_of_date: string };

const ASSET_TYPES = ["Investment Account", "Real Estate", "Vehicle", "Cash", "Cryptocurrency", "Other"];
const LIABILITY_TYPES = ["Mortgage", "Auto Loan", "Student Loan", "Personal Loan", "Other"];

const today = new Date().toISOString().split("T")[0];
const emptyAsset = { name: "", asset_type: ASSET_TYPES[0], current_value: "", as_of_date: today };
const emptyLiability = { name: "", liability_type: LIABILITY_TYPES[0], current_balance: "", as_of_date: today };

export default function NetWorth() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [editingLiability, setEditingLiability] = useState<Liability | null>(null);
  const [assetForm, setAssetForm] = useState(emptyAsset);
  const [liabilityForm, setLiabilityForm] = useState(emptyLiability);
  const [showAssetForm, setShowAssetForm] = useState(false);
  const [showLiabilityForm, setShowLiabilityForm] = useState(false);

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
  const deleteAssetMut = useMutation({ mutationFn: (id: number) => netWorthApi.removeAsset(id), onSuccess: invalidate });

  const createLiabilityMut = useMutation({
    mutationFn: (d: object) => netWorthApi.createLiability(d),
    onSuccess: () => { invalidate(); setShowLiabilityForm(false); setLiabilityForm(emptyLiability); },
  });
  const updateLiabilityMut = useMutation({
    mutationFn: ({ id, d }: { id: number; d: object }) => netWorthApi.updateLiability(id, d),
    onSuccess: () => { invalidate(); setEditingLiability(null); },
  });
  const deleteLiabilityMut = useMutation({ mutationFn: (id: number) => netWorthApi.removeLiability(id), onSuccess: invalidate });
  const snapshotMut = useMutation({ mutationFn: netWorthApi.snapshot, onSuccess: invalidate });

  const chartData = (history as any[]).map((s: any) => ({
    date: s.snapshot_date,
    netWorth: parseFloat(s.net_worth),
  }));

  const nw = totals?.net_worth != null ? parseFloat(totals.net_worth) : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Net Worth <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500">Assets, liabilities, and net worth over time</p>
        </div>
        <button
          className="btn btn-primary flex items-center gap-2"
          onClick={() => snapshotMut.mutate()}
          disabled={snapshotMut.isPending}
        >
          <Camera className="w-4 h-4" />
          {snapshotMut.isPending ? "Saving…" : "Capture Snapshot"}
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Manual Assets</p>
          <p className="text-lg font-bold text-emerald-600">{totals ? fmt(parseFloat(totals.total_assets)) : "—"}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Account Balances</p>
          <p className="text-lg font-bold text-emerald-600">{totals ? fmt(parseFloat(totals.account_balances)) : "—"}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Liabilities</p>
          <p className="text-lg font-bold text-red-500">
            {totals ? fmt(parseFloat(totals.card_balances) + parseFloat(totals.total_liabilities)) : "—"}
          </p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Net Worth</p>
          <p className={`text-2xl font-bold ${nw != null && nw >= 0 ? "text-emerald-600" : "text-red-500"}`}>
            {nw != null ? fmt(nw) : "—"}
          </p>
        </div>
      </div>

      {/* Trend Chart */}
      {chartData.length > 0 ? (
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">Net Worth Over Time</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => fmt(v)} />
              <Line type="monotone" dataKey="netWorth" stroke="#6366f1" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="card text-center py-6 text-gray-400 text-sm">
          No snapshots yet — click "Capture Snapshot" to start your trend line.
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
                <span className="font-semibold text-emerald-600">{fmt(parseFloat(a.current_value))}</span>
                <button onClick={() => { setEditingAsset(a); setShowAssetForm(false); }} className="text-gray-400 hover:text-indigo-600"><Pencil className="w-4 h-4" /></button>
                <button onClick={() => deleteAssetMut.mutate(a.id)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
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
                <span className="font-semibold text-red-500">{fmt(parseFloat(l.current_balance))}</span>
                <button onClick={() => { setEditingLiability(l); setShowLiabilityForm(false); }} className="text-gray-400 hover:text-indigo-600"><Pencil className="w-4 h-4" /></button>
                <button onClick={() => deleteLiabilityMut.mutate(l.id)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
          ))}
        </div>
      </div>
      {showHelp && <HelpPanel title="Net Worth" body={"Your net worth = assets + account balances − credit card balances − liabilities.\n\nAdd manual assets (investments, real estate, vehicles) and liabilities (mortgage, loans).\n\nClick 'Capture Snapshot' to save today's net worth and build a trend line over time."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}
