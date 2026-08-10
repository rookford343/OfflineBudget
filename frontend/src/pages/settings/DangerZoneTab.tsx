import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi, dataApi } from "../../api";
import { clearAuth } from "../../store/auth";

export default function DangerZoneTab() {
  const qc = useQueryClient();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteAccountMut = useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: () => { clearAuth(); window.location.href = "/login"; },
    onError: (e: any) => setDeleteError(e?.response?.data?.detail ?? "Failed to delete account"),
  });
  function handleDeleteAccount() { setDeleteError(null); deleteAccountMut.mutate({ password: deletePassword }); }

  const [clearConfirm, setClearConfirm] = useState<"transactions" | "cc-transactions" | null>(null);
  const clearTxnMut = useMutation({
    mutationFn: dataApi.clearTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setClearConfirm(null);
    },
  });
  const clearCCTxnMut = useMutation({
    mutationFn: dataApi.clearCCTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cc-transactions"] });
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      setClearConfirm(null);
    },
  });

  return (
    <div className="card border-red-100 dark:border-red-900/30">
      <h3 className="text-sm font-semibold text-red-600 dark:text-red-400 mb-3">Danger Zone</h3>
      <div className="space-y-4">

        {/* Clear checking transactions */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
          {clearConfirm !== "transactions" ? (
            <button onClick={() => { setClearConfirm("transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
              Clear all checking transactions…
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-600">This permanently deletes all checking transactions and resets all account balances to $0. Your accounts, categories, and settings are kept.</p>
              <div className="flex gap-2">
                <button onClick={() => clearTxnMut.mutate()} disabled={clearTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                  {clearTxnMut.isPending ? "Clearing…" : "Yes, clear transactions"}
                </button>
                <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400">Keeps accounts, categories, recurring items, and rules.</p>
        </div>

        {/* Clear CC transactions */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
          {clearConfirm !== "cc-transactions" ? (
            <button onClick={() => { setClearConfirm("cc-transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
              Clear all credit card transactions…
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-600">This permanently deletes all credit card transactions and resets all card balances to $0. Your cards, categories, and settings are kept.</p>
              <div className="flex gap-2">
                <button onClick={() => clearCCTxnMut.mutate()} disabled={clearCCTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                  {clearCCTxnMut.isPending ? "Clearing…" : "Yes, clear CC transactions"}
                </button>
                <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400">Keeps cards, categories, recurring items, and rules.</p>
        </div>

        {/* Delete entire account */}
        <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
        {!showDeleteConfirm ? (
          <button onClick={() => { setShowDeleteConfirm(true); setClearConfirm(null); }} className="text-sm text-red-600 hover:underline">
            Delete my account and all data…
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-red-600">This permanently deletes all your accounts, transactions, and settings. Enter your password to confirm.</p>
            <div className="flex flex-wrap items-center gap-2 max-w-sm">
              <input type="password" className="input text-sm flex-1 min-w-0" placeholder="Your password" value={deletePassword} onChange={e => setDeletePassword(e.target.value)} />
              <button onClick={handleDeleteAccount} disabled={deleteAccountMut.isPending || !deletePassword} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg font-medium">
                {deleteAccountMut.isPending ? "Deleting…" : "Delete"}
              </button>
              <button onClick={() => { setShowDeleteConfirm(false); setDeletePassword(""); setDeleteError(null); }} className="btn-secondary text-sm px-3">Cancel</button>
            </div>
            {deleteError && <p className="text-xs text-red-600">{deleteError}</p>}
          </div>
        )}
        <p className="text-xs text-gray-400">Permanently removes your login, all accounts, and every piece of data.</p>
        </div>

      </div>
    </div>
  );
}
