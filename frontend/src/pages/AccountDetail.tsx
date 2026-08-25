import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, transactionsApi } from "../api";
import { fmt, fmtDate } from "../lib/utils";
import { ArrowLeft } from "lucide-react";

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const accountId = Number(id);

  const { data: account, isLoading: accountLoading, isError: accountError } = useQuery({
    queryKey: ["account", accountId],
    queryFn: () => accountsApi.get(accountId),
    enabled: Number.isFinite(accountId),
  });

  const { data: allTransactions = [], isLoading: txnsLoading } = useQuery({
    queryKey: ["transactions", { account_id: accountId }],
    queryFn: () => transactionsApi.list({ account_id: accountId }),
    enabled: Number.isFinite(accountId),
  });
  // Backend has no `limit` param (confirmed: backend/routers/transactions.py
  // list_transactions signature) but already returns date-descending, so the
  // most recent 25 is just the first 25 of what comes back.
  const transactions = allTransactions.slice(0, 25);

  if (!Number.isFinite(accountId) || accountError) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-500 dark:text-gray-400">Account not found.</p>
        <Link to="/dashboard" className="text-indigo-600 dark:text-indigo-400 text-sm font-medium">
          ← Back to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link to="/dashboard" className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400">
        <ArrowLeft size={14} /> Back
      </Link>

      {accountLoading && <div className="card text-sm text-gray-400 dark:text-gray-500">Loading…</div>}

      {account && (
        <div className="card">
          <p className="text-xs uppercase tracking-wide text-gray-400 dark:text-gray-500">{account.type}</p>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{account.name}</h2>
          <p className={`text-3xl font-bold ${parseFloat(account.current_balance) < 0 ? "text-red-500 dark:text-red-400" : "text-gray-900 dark:text-white"} mt-2`}>{fmt(account.current_balance)}</p>
        </div>
      )}

      <div className="card">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Recent Transactions</h3>
        {txnsLoading && <p className="text-sm text-gray-400 dark:text-gray-500">Loading…</p>}
        {!txnsLoading && transactions.length === 0 && (
          <p className="text-sm text-gray-400 dark:text-gray-500">No transactions for this account yet.</p>
        )}
        {!txnsLoading && transactions.length > 0 && (
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {transactions.map((t: any) => (
              <li key={t.id} className="py-2 flex items-center justify-between text-sm">
                <div className="min-w-0">
                  <p className="text-gray-900 dark:text-gray-100 truncate">{t.description}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">{fmtDate(t.date)}</p>
                </div>
                <span className={`font-semibold tabular-nums shrink-0 ml-3 ${parseFloat(t.amount) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {parseFloat(t.amount) >= 0 ? "+" : ""}{fmt(t.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Link to="/transactions" className="inline-block mt-3 text-sm text-indigo-600 dark:text-indigo-400 font-medium">
          View all in Transactions →
        </Link>
      </div>
    </div>
  );
}
