import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, cardsApi, bankSyncApi } from "../../api";
import { fmt, parseServerDateTime } from "../../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../../store/balanceVisibility";
import { openPlaidLink } from "../../lib/plaidLink";
import { Plus, Pencil, Trash2, X, Check, AlertTriangle, Link, RefreshCw } from "lucide-react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { byName } from "../../lib/selectOptions";
import PlaidFirstImportPreview from "./PlaidFirstImportPreview";

const emptyAccount = { name: "", type: "checking", current_balance: "0", low_balance_threshold: "", interest_rate: "", notes: "", is_emergency_fund: false };

// Names the connection that already syncs an account, from the /link 409's
// `existing_provider`. Unknown or missing falls back to a neutral phrase.
function providerLabel(provider: string | null): string {
  if (provider === "simplefin") return "SimpleFIN";
  if (provider === "plaid") return "Plaid";
  return "another connection";
}

export default function AccountsTab() {
  const qc = useQueryClient();
  const balancesHidden = useBalancesHidden();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  // Credit cards are linkable sync targets too -- the mapping dropdown below
  // offers them alongside checking accounts.
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: bankConnections = [] } = useQuery<any[]>({ queryKey: ["bank-connections"], queryFn: bankSyncApi.status });
  const [setupToken, setSetupToken] = useState("");
  const [pendingConnect, setPendingConnect] = useState<{ connection_id: number; accounts: any[] } | null>(null);
  const [linkTargets, setLinkTargets] = useState<Record<string, string>>({});
  // Set only when a /link call 409'd because another connection's active
  // link already targets the same local account/card -- turns that one row
  // into an inline "switch to this provider?" prompt instead of a dead end.
  const [switchPrompt, setSwitchPrompt] = useState<
    { accountId: string; connectionId: number; existingProvider: string | null } | null
  >(null);

  const connectMut = useMutation({
    mutationFn: (token: string) => bankSyncApi.connect(token),
    onSuccess: (data) => { setPendingConnect(data); setSetupToken(""); },
  });
  const linkMut = useMutation({
    mutationFn: ({ connectionId, data }: any) => bankSyncApi.link(connectionId, data),
    onSuccess: (_data, variables: any) => {
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      setSwitchPrompt(null);
      setLinkTargets((prev) => {
        const next = { ...prev };
        delete next[variables.data.simplefin_account_id];
        return next;
      });
    },
    onError: (err: any, variables: any) => {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 409 && detail?.existing_link_id) {
        setSwitchPrompt({
          accountId: variables.data.simplefin_account_id,
          connectionId: variables.connectionId,
          existingProvider: detail.existing_provider ?? null,
        });
      }
      // Any other failure still reaches the user via the global error toast
      // (main.tsx's MutationCache.onError) -- nothing else to do here.
    },
  });
  // Re-opens the mapping UI for a connection whose /connect or /plaid/exchange
  // response is long gone -- without this, an unmapped account needs a whole
  // new setup token (SimpleFIN) or Link session (Plaid).
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
      // New synced rows can reorder/replace what the Dashboard's Recent
      // transactions card shows, same as accounts/credit-cards above.
      qc.invalidateQueries({ queryKey: ["recent-activity"] });
      setSyncResult(data);
      setTimeout(() => setSyncResult(null), 6000);
    },
  });
  const disconnectMut = useMutation({
    mutationFn: bankSyncApi.disconnect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      setDeleteConnection(null);
    },
  });

  // ── Plaid: connect, reconnect, first-import preview ───────────────────────
  // A fresh connection: link-token (no connection_id) -> Link -> exchange.
  // `null` means the user closed Link without finishing -- not an error.
  const plaidConnectMut = useMutation({
    mutationFn: async () => {
      const { link_token } = await bankSyncApi.plaidLinkToken();
      const opened = await openPlaidLink(link_token);
      if (!opened) return null;
      return bankSyncApi.plaidExchange(opened.publicToken);
    },
    onSuccess: (data) => {
      if (!data) return;
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      setPendingConnect(data);
    },
  });
  // Reconnecting an errored item: link-token in update mode -> Link. Plaid
  // clears the item's error state itself once the re-auth lands; there's no
  // separate "finish reconnect" call on this backend. The connection's own
  // status only flips back to active on its next sync, so run one now rather
  // than leave the error showing until the next scheduled slot.
  const plaidReconnectMut = useMutation({
    mutationFn: async (connectionId: number) => {
      const { link_token } = await bankSyncApi.plaidLinkToken(connectionId);
      return openPlaidLink(link_token);
    },
    onSuccess: (opened) => {
      if (!opened) return;
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      // syncNowMut calls bankSyncApi.syncNow() and, on success, invalidates
      // bank-connections again (plus balances and recent activity).
      syncNowMut.mutate();
    },
  });
  const [firstImportPreview, setFirstImportPreview] = useState<{ connectionId: number; data: any } | null>(null);
  const previewImportMut = useMutation({
    mutationFn: (connectionId: number) => bankSyncApi.plaidFirstImport(connectionId, false),
    onSuccess: (data, connectionId) => setFirstImportPreview({ connectionId, data }),
  });
  const confirmImportMut = useMutation({
    mutationFn: (connectionId: number) => bankSyncApi.plaidFirstImport(connectionId, true),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bank-connections"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      qc.invalidateQueries({ queryKey: ["cards"] });
      qc.invalidateQueries({ queryKey: ["recent-activity"] });
      setFirstImportPreview(null);
    },
  });

  function submitLink(simplefinAccountId: string, simplefinAccountName: string, connectionId: number, switchExisting = false) {
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
        switch_existing: switchExisting,
      },
    });
  }

  const [showAccForm, setShowAccForm] = useState(false);
  const [editAcc, setEditAcc] = useState<any | null>(null);
  const [accForm, setAccForm] = useState({ ...emptyAccount });
  const [deleteAccId, setDeleteAccId] = useState<number | null>(null);
  const [deleteConnection, setDeleteConnection] = useState<any | null>(null);
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
      is_emergency_fund: accForm.is_emergency_fund,
    };
    if (editAcc) updateAccMut.mutate({ id: editAcc.id, data });
    else createAccMut.mutate(data);
  }
  function openNewAcc() { setAccForm({ ...emptyAccount }); setEditAcc(null); setShowAccForm(true); }
  function openEditAcc(a: any) {
    setEditAcc(a);
    setAccForm({ name: a.name, type: a.type, current_balance: a.current_balance, low_balance_threshold: a.low_balance_threshold ?? "", interest_rate: a.interest_rate ?? "", notes: a.notes ?? "", is_emergency_fund: a.is_emergency_fund ?? false });
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
                    {maskIfHidden(balancesHidden, fmt(a.current_balance))}
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
            Connects to your bank via SimpleFIN Bridge (~$15/yr, read-only) or Plaid to pull transactions automatically.
            Plaid accounts sync at 7am, 11am, 3pm and 7pm. SimpleFIN accounts sync at 7am.
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
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      Connection #{conn.id} — {conn.status}
                    </p>
                    <span className={conn.provider === "plaid" ? "badge-blue" : "badge-green"}>
                      {conn.provider === "plaid" ? "Plaid" : "SimpleFIN"}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {conn.last_synced_at ? `Last synced ${parseServerDateTime(conn.last_synced_at).toLocaleString(undefined, { timeZoneName: "short" })}` : "Never synced"}
                  </p>
                  {conn.last_error && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertTriangle size={12} /> {conn.last_error}</p>}
                </div>
                <div className="flex items-center gap-1">
                  {conn.provider === "plaid" && conn.status === "error" && (
                    <button
                      onClick={() => plaidReconnectMut.mutate(conn.id)}
                      disabled={plaidReconnectMut.isPending}
                      className="btn-ghost text-xs px-2 py-1 text-indigo-500 hover:bg-indigo-50 flex items-center gap-1"
                    >
                      <RefreshCw size={12} />
                      {plaidReconnectMut.isPending && plaidReconnectMut.variables === conn.id ? "Reconnecting…" : "Reconnect"}
                    </button>
                  )}
                  {conn.provider === "plaid" && conn.links.length > 0 && !conn.first_import_done && (
                    <button
                      onClick={() => previewImportMut.mutate(conn.id)}
                      disabled={previewImportMut.isPending}
                      className="btn-ghost text-xs px-2 py-1 text-indigo-500 hover:bg-indigo-50"
                    >
                      {previewImportMut.isPending && previewImportMut.variables === conn.id ? "Loading…" : "Preview first import"}
                    </button>
                  )}
                  <button
                    onClick={() => loadAccountsMut.mutate(conn.id)}
                    disabled={loadAccountsMut.isPending}
                    className="btn-ghost text-xs px-2 py-1 text-indigo-500 hover:bg-indigo-50"
                  >
                    {loadAccountsMut.isPending && loadAccountsMut.variables === conn.id ? "Loading…" : "Map more accounts"}
                  </button>
                  <button onClick={() => setDeleteConnection(conn)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
                </div>
              </div>
              {conn.links.length > 0 && (
                <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700">
                  {conn.links.map((l: any) => (
                    <div key={l.id} className={`py-1.5 text-xs ${l.is_active ? "text-gray-600 dark:text-gray-300" : "text-gray-400 dark:text-gray-500"}`}>
                      {l.simplefin_account_name} → {l.local_account_id ? "linked account" : l.local_credit_card_id ? "linked card" : "unlinked"}
                      {!l.is_active && " (switched to another connection)"}
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
                  <span className="text-xs text-gray-600 dark:text-gray-300">
                    {a.mask
                      ? `${a.name} ••${a.mask} (${a.kind ?? "account"})`
                      : `${a.org_name} — ${a.name} (${fmt(a.balance)})`}
                  </span>
                  {switchPrompt && switchPrompt.accountId === a.simplefin_account_id && switchPrompt.connectionId === pendingConnect.connection_id ? (
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-amber-600 dark:text-amber-400">
                        Already synced by {providerLabel(switchPrompt.existingProvider)}. Switch to this one?
                      </span>
                      <button
                        onClick={() => submitLink(a.simplefin_account_id, a.name, pendingConnect.connection_id, true)}
                        disabled={linkMut.isPending}
                        className="btn-primary btn-sm text-xs px-2 py-1"
                      >
                        Switch
                      </button>
                      <button onClick={() => setSwitchPrompt(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                    </div>
                  ) : (
                    <>
                      <select
                        className="input py-1 text-xs w-40"
                        value={linkTargets[a.simplefin_account_id] || ""}
                        onChange={(e) => setLinkTargets({ ...linkTargets, [a.simplefin_account_id]: e.target.value })}
                      >
                        <option value="">Select account or card…</option>
                        <optgroup label="Accounts">
                          {byName(accounts).map((acc: any) => <option key={`account:${acc.id}`} value={`account:${acc.id}`}>{acc.name}</option>)}
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
                    </>
                  )}
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
            <button
              onClick={() => plaidConnectMut.mutate()}
              disabled={plaidConnectMut.isPending}
              className="btn-secondary btn-sm text-xs px-3 py-1.5 whitespace-nowrap"
            >
              {plaidConnectMut.isPending ? "Connecting…" : "Connect with Plaid"}
            </button>
          </div>
          {connectMut.isError && <p className="text-xs text-red-600 dark:text-red-400">{(connectMut.error as any)?.response?.data?.detail || "Failed to connect"}</p>}
          {plaidConnectMut.isError && <p className="text-xs text-red-600 dark:text-red-400">{(plaidConnectMut.error as any)?.response?.data?.detail || "Failed to connect with Plaid"}</p>}
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
              {/* Intent, not product type: a money market can be either an
                  emergency fund or ordinary savings, and only the owner knows
                  which. Flagged accounts are held out of any "can I cover
                  this?" figure so untouchable money never pads it. */}
              <div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" className="mt-0.5" checked={accForm.is_emergency_fund}
                    onChange={e => setAccForm({ ...accForm, is_emergency_fund: e.target.checked })} />
                  <span>
                    <span className="text-sm text-gray-800 dark:text-gray-200">Emergency fund</span>
                    <span className="block text-xs text-gray-500 dark:text-gray-400">
                      Money you don't plan to spend. Excluded from available-savings figures.
                    </span>
                  </span>
                </label>
              </div>
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
      <ConfirmDialog
        open={!!deleteConnection}
        onOpenChange={(open) => !open && setDeleteConnection(null)}
        icon={Trash2}
        title="Disconnect this bank connection?"
        description={`This stops automatic syncing for ${deleteConnection?.links?.length ? deleteConnection.links.map((l: any) => l.simplefin_account_name).join(", ") : `connection #${deleteConnection?.id}`}. Past imported transactions are not affected, but you'll need to reconnect to sync again.`}
        confirmLabel="Disconnect"
        confirmingLabel="Disconnecting…"
        isPending={disconnectMut.isPending}
        onConfirm={() => deleteConnection && disconnectMut.mutate(deleteConnection.id)}
      />

      {firstImportPreview && (
        <PlaidFirstImportPreview
          data={firstImportPreview.data}
          onClose={() => setFirstImportPreview(null)}
          onConfirm={() => confirmImportMut.mutate(firstImportPreview.connectionId)}
          confirming={confirmImportMut.isPending}
        />
      )}
    </div>
  );
}
