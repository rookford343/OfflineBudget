import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, cardsApi, bankSyncApi } from "../../api";
import { fmt, parseServerDateTime } from "../../lib/utils";
import { Plus, Pencil, Trash2, X, Check, AlertTriangle, Link } from "lucide-react";

const emptyAccount = { name: "", type: "checking", current_balance: "0", low_balance_threshold: "", interest_rate: "", notes: "" };

export default function AccountsTab() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  // Credit cards are linkable sync targets too -- the mapping dropdown below
  // offers them alongside checking accounts.
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: bankConnections = [] } = useQuery<any[]>({ queryKey: ["bank-connections"], queryFn: bankSyncApi.status });
  const [setupToken, setSetupToken] = useState("");
  const [pendingConnect, setPendingConnect] = useState<{ connection_id: number; accounts: any[] } | null>(null);
  const [linkTargets, setLinkTargets] = useState<Record<string, string>>({});

  const connectMut = useMutation({
    mutationFn: (token: string) => bankSyncApi.connect(token),
    onSuccess: (data) => { setPendingConnect(data); setSetupToken(""); },
  });
  const linkMut = useMutation({
    mutationFn: ({ connectionId, data }: any) => bankSyncApi.link(connectionId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["bank-connections"] }); },
  });
  // Re-opens the mapping UI for a connection whose /connect response is long
  // gone -- without this, an unmapped account needs a whole new setup token.
  const loadAccountsMut = useMutation({
    mutationFn: (connectionId: number) => bankSyncApi.accounts(connectionId),
    onSuccess: (accts: any[], connectionId: number) =>
      setPendingConnect({ connection_id: connectionId, accounts: accts }),
  });
  const [syncResult, setSyncResult] = useState<{ imported: number; skipped_duplicates: number } | null>(null);
  const syncNowMut = useMutation({
    mutationFn: bankSyncApi.syncNow,
    onSuccess: (data: { imported: number; skipped_duplicates: number }) => {
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      // A sync updates linked card balances too, so refresh both keys the
      // codebase uses for credit cards.
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      qc.invalidateQueries({ queryKey: ["cards"] });
      setSyncResult(data);
      setTimeout(() => setSyncResult(null), 6000);
    },
  });
  const disconnectMut = useMutation({
    mutationFn: bankSyncApi.disconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bank-connections"] }),
  });

  function submitLink(simplefinAccountId: string, simplefinAccountName: string, connectionId: number) {
    const target = linkTargets[simplefinAccountId];
    if (!target) return;
    const [kind, id] = target.split(":");
    linkMut.mutate({
      connectionId,
      data: {
        simplefin_account_id: simplefinAccountId,
        simplefin_account_name: simplefinAccountName,
        local_account_id: kind === "account" ? parseInt(id) : undefined,
        local_credit_card_id: kind === "card" ? parseInt(id) : undefined,
      },
    });
  }

  const [showAccForm, setShowAccForm] = useState(false);
  const [editAcc, setEditAcc] = useState<any | null>(null);
  const [accForm, setAccForm] = useState({ ...emptyAccount });
  const [deleteAccId, setDeleteAccId] = useState<number | null>(null);
  const [editBalId, setEditBalId] = useState<number | null>(null);
  const [newBal, setNewBal] = useState("");
  const createAccMut = useMutation({ mutationFn: accountsApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setShowAccForm(false); } });
  const updateAccMut = useMutation({ mutationFn: ({ id, data }: any) => accountsApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setEditAcc(null); setShowAccForm(false); setEditBalId(null); } });
  const deleteAccMut = useMutation({ mutationFn: accountsApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setDeleteAccId(null); } });

  function submitAcc(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      ...accForm,
      current_balance: parseFloat(accForm.current_balance),
      low_balance_threshold: accForm.low_balance_threshold ? parseFloat(accForm.low_balance_threshold) : null,
      interest_rate: accForm.interest_rate ? parseFloat(accForm.interest_rate) : null,
    };
    if (editAcc) updateAccMut.mutate({ id: editAcc.id, data });
    else createAccMut.mutate(data);
  }
  function openNewAcc() { setAccForm({ ...emptyAccount }); setEditAcc(null); setShowAccForm(true); }
  function openEditAcc(a: any) {
    setEditAcc(a);
    setAccForm({ name: a.name, type: a.type, current_balance: a.current_balance, low_balance_threshold: a.low_balance_threshold ?? "", interest_rate: a.interest_rate ?? "", notes: a.notes ?? "" });
    setShowAccForm(true);
  }

  return (
    <div className="space-y-6">
      {/* ── Accounts ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Accounts</h3>
          <button onClick={openNewAcc} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Account</button>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {accounts.map((a: any) => (
            <div key={a.id} className="py-3 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{a.name}</p>
                  {a.low_balance_threshold && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold) && (
                    <AlertTriangle size={14} className="text-amber-500" />
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{a.type.replace("_", " ")}</p>
                {a.low_balance_threshold && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">Alert below {fmt(a.low_balance_threshold)}</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {editBalId === a.id ? (
                  <div className="flex flex-col items-end gap-1">
                    <div className="flex items-center gap-1">
                      <input type="number" step="0.01" className="input w-28 py-1 text-right" value={newBal} onChange={e => setNewBal(e.target.value)} autoFocus />
                      <button onClick={() => updateAccMut.mutate({ id: a.id, data: { current_balance: parseFloat(newBal) } })} className="text-green-600"><Check size={14} /></button>
                      <button onClick={() => setEditBalId(null)} className="text-gray-400"><X size={14} /></button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => { setEditBalId(a.id); setNewBal(a.current_balance); }} className="text-sm font-bold text-gray-900 dark:text-gray-100 tabular-nums hover:text-indigo-600 transition-colors" title="Click to correct balance">
                    {fmt(a.current_balance)}
                  </button>
                )}
                <button onClick={() => openEditAcc(a)} className="btn-ghost p-1.5"><Pencil size={14} /></button>
                <button onClick={() => setDeleteAccId(a.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
          {accounts.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">No accounts yet</p>}
        </div>
      </div>

      {/* ── Bank Connections ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Link size={16} className="text-indigo-500" /> Bank Connections</h3>
          {bankConnections.length > 0 && (
            <button onClick={() => syncNowMut.mutate()} disabled={syncNowMut.isPending} className="btn-primary btn-sm text-xs px-3 py-1.5">
              {syncNowMut.isPending ? "Syncing…" : "Sync Now"}
            </button>
          )}
        </div>
        <div className="space-y-4">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Connects to your bank via SimpleFIN Bridge (~$15/yr, read-only) to pull transactions automatically. Syncs daily at 5am ET.
          </p>
          {syncResult && (
            <p className="text-xs text-emerald-600 dark:text-emerald-400">
              {syncResult.imported > 0
                ? `✓ ${syncResult.imported} new transaction${syncResult.imported === 1 ? "" : "s"}${syncResult.skipped_duplicates > 0 ? ` (${syncResult.skipped_duplicates} already had)` : ""}`
                : "✓ Up to date — nothing new since your bank's last refresh"}
            </p>
          )}

          {bankConnections.map((conn: any) => (
            <div key={conn.id} className="border border-gray-100 dark:border-gray-700 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    Connection #{conn.id} — {conn.status}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {conn.last_synced_at ? `Last synced ${parseServerDateTime(conn.last_synced_at).toLocaleString(undefined, { timeZoneName: "short" })}` : "Never synced"}
                  </p>
                  {conn.last_error && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertTriangle size={12} /> {conn.last_error}</p>}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => loadAccountsMut.mutate(conn.id)}
                    disabled={loadAccountsMut.isPending}
                    className="btn-ghost text-xs px-2 py-1 text-indigo-500 hover:bg-indigo-50"
                  >
                    {loadAccountsMut.isPending && loadAccountsMut.variables === conn.id ? "Loading…" : "Map more accounts"}
                  </button>
                  <button onClick={() => disconnectMut.mutate(conn.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
                </div>
              </div>
              {conn.links.length > 0 && (
                <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700">
                  {conn.links.map((l: any) => (
                    <div key={l.id} className="py-1.5 text-xs text-gray-600 dark:text-gray-300">
                      {l.simplefin_account_name} → {l.local_account_id ? "linked account" : l.local_credit_card_id ? "linked card" : "unlinked"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {pendingConnect && (
            <div className="border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 space-y-2">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">Map discovered accounts</p>
              {pendingConnect.accounts.map((a: any) => (
                <div key={a.simplefin_account_id} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-gray-600 dark:text-gray-300">{a.org_name} — {a.name} ({fmt(a.balance)})</span>
                  <select
                    className="input py-1 text-xs w-40"
                    value={linkTargets[a.simplefin_account_id] || ""}
                    onChange={(e) => setLinkTargets({ ...linkTargets, [a.simplefin_account_id]: e.target.value })}
                  >
                    <option value="">Select account or card…</option>
                    <optgroup label="Accounts">
                      {accounts.map((acc: any) => <option key={`account:${acc.id}`} value={`account:${acc.id}`}>{acc.name}</option>)}
                    </optgroup>
                    <optgroup label="Credit Cards">
                      {cards.map((c: any) => <option key={`card:${c.id}`} value={`card:${c.id}`}>{c.name}</option>)}
                    </optgroup>
                  </select>
                  <button
                    onClick={() => submitLink(a.simplefin_account_id, a.name, pendingConnect.connection_id)}
                    disabled={!linkTargets[a.simplefin_account_id]}
                    className="btn-primary btn-sm text-xs px-2 py-1"
                  >
                    Link
                  </button>
                </div>
              ))}
              <button onClick={() => setPendingConnect(null)} className="text-xs text-gray-400 hover:text-gray-600">Done</button>
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="text"
              className="input flex-1 text-xs"
              placeholder="Paste SimpleFIN setup token"
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
            />
            <button
              onClick={() => connectMut.mutate(setupToken)}
              disabled={!setupToken || connectMut.isPending}
              className="btn-primary btn-sm text-xs px-3 py-1.5"
            >
              {connectMut.isPending ? "Connecting…" : "Connect"}
            </button>
          </div>
          {connectMut.isError && <p className="text-xs text-red-600 dark:text-red-400">{(connectMut.error as any)?.response?.data?.detail || "Failed to connect"}</p>}
        </div>
      </div>

      {/* ── Add/Edit Account modal ── */}
      {showAccForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editAcc ? "Edit Account" : "Add Account"}</h3>
              <button onClick={() => setShowAccForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitAcc} className="space-y-3">
              <div><label className="label">Name</label><input className="input" placeholder="Main Checking" value={accForm.name} onChange={e => setAccForm({ ...accForm, name: e.target.value })} required /></div>
              <div>
                <label className="label">Type</label>
                <select className="input" value={accForm.type} onChange={e => setAccForm({ ...accForm, type: e.target.value })}>
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="money_market">Money Market</option>
                </select>
              </div>
              <div><label className="label">Current Balance</label><input type="number" step="0.01" className="input" value={accForm.current_balance} onChange={e => setAccForm({ ...accForm, current_balance: e.target.value })} /></div>
              <div><label className="label">Warn When Balance Drops Below (optional)</label><input type="number" step="0.01" className="input" placeholder="e.g. 1000" value={accForm.low_balance_threshold} onChange={e => setAccForm({ ...accForm, low_balance_threshold: e.target.value })} /></div>
              <div><label className="label">Annual Interest Rate % (optional, for savings/HYSA)</label><input type="number" step="0.01" className="input" placeholder="e.g. 4.5" value={accForm.interest_rate} onChange={e => setAccForm({ ...accForm, interest_rate: e.target.value })} /></div>
              <div><label className="label">Notes</label><input className="input" value={accForm.notes} onChange={e => setAccForm({ ...accForm, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editAcc ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowAccForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete account confirm ── */}
      {deleteAccId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Remove this account?</h3>
            <p className="text-sm text-gray-500 mb-5">It will be hidden but data is preserved.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteAccMut.mutate(deleteAccId)} className="btn-danger flex-1">Remove</button>
              <button onClick={() => setDeleteAccId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
