import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { accountsApi, cardsApi, recurringApi, analyticsApi } from "../api";
import { fmt, utilColor, utilBg } from "../lib/utils";
import { CreditCard, Calendar, AlertCircle, AlertTriangle, Wallet, BookOpen, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { TrendBadge } from "../components/TrendBadge";
import { SparkLine } from "../components/SparkLine";
import { RiskBanner } from "../components/RiskBanner";

const DASHBOARD_HELP = `The Dashboard gives you a real-time snapshot of your financial health.

Key sections:
• Available to Spend — income minus bills minus what you've already spent
• Account balances — all checking and savings accounts
• Credit card balances and amounts due
• Monthly narrative summary — plain-English recap
• Upcoming bills — items due in the next 30 days`;

export default function Dashboard() {
  const navigate = useNavigate();
  const [showHelp, setShowHelp] = useState(false);
  const now = new Date();
  // Show previous month's summary once we're past the 3rd of the current month; otherwise current month
  const summaryMonth = now.getDate() > 3 ? now.getMonth() + 1 : (now.getMonth() === 0 ? 12 : now.getMonth());
  const summaryYear = now.getDate() > 3 ? now.getFullYear() : (now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear());

  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checkingAccounts = accounts.filter((a) => a.type === "checking");
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: recurring = [] } = useQuery<any[]>({ queryKey: ["recurring"], queryFn: () => recurringApi.list(true) });
  const { data: ats } = useQuery<any>({ queryKey: ["available-to-spend"], queryFn: analyticsApi.availableToSpend });
  const { data: summary } = useQuery<any>({
    queryKey: ["monthly-summary", summaryYear, summaryMonth],
    queryFn: () => analyticsApi.monthlySummary(summaryYear, summaryMonth),
  });
  const { data: rollingRaw = [] } = useQuery<{ month: string; total: string }[]>({
    queryKey: ["rolling-monthly-6"],
    queryFn: () => analyticsApi.rollingMonthly(6),
  });
  const primaryChecking = checkingAccounts[0];
  const { data: weeklyDigest } = useQuery<any>({
    queryKey: ["weekly-digest", primaryChecking?.id],
    queryFn: () => analyticsApi.weeklyDigest(primaryChecking.id),
    enabled: !!primaryChecking,
  });

  const totalChecking = checkingAccounts.reduce((s: number, a: any) => s + parseFloat(a.current_balance), 0);
  const anyBelowThreshold = checkingAccounts.some((a: any) =>
    a.low_balance_threshold != null && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold)
  );
  const totalCards = cards.reduce((s: number, c: any) => s + parseFloat(c.current_balance), 0);
  const totalCardsDue = cards.reduce((s: number, c: any) => s + parseFloat(c.balance_due), 0);

  // Upcoming bills in next 30 days
  const todayDate = new Date();
  const upcoming = recurring
    .filter((r) => r.type === "expense")
    .map((r: any) => {
      const dom = r.day_of_month === 0 ? new Date(todayDate.getFullYear(), todayDate.getMonth() + 1, 0).getDate() : r.day_of_month;
      const next = new Date(todayDate.getFullYear(), todayDate.getMonth(), dom);
      if (next < todayDate) next.setMonth(next.getMonth() + 1);
      return { ...r, next_date: next };
    })
    .filter((r) => (r.next_date.getTime() - todayDate.getTime()) / 86400000 <= 30)
    .sort((a, b) => a.next_date.getTime() - b.next_date.getTime());

  // Next paycheck
  const nextPaycheck = recurring
    .filter((r) => r.type === "income")
    .map((r: any) => {
      const dom = r.day_of_month === 0 ? new Date(todayDate.getFullYear(), todayDate.getMonth() + 1, 0).getDate() : r.day_of_month;
      const next = new Date(todayDate.getFullYear(), todayDate.getMonth(), dom);
      if (next <= todayDate) next.setMonth(next.getMonth() + 1);
      return { ...r, next_date: next };
    })
    .sort((a, b) => a.next_date.getTime() - b.next_date.getTime())[0];

  // Sparkline + month-over-month % for the Net Position card.
  const rolling = [...rollingRaw].sort((a, b) => a.month.localeCompare(b.month));
  const sparkData = rolling.map((r) => parseFloat(r.total));
  const momPct: number | null = rolling.length >= 2
    ? (() => {
        const cur = parseFloat(rolling[rolling.length - 1].total);
        const prev = parseFloat(rolling[rolling.length - 2].total);
        return prev === 0 ? null : ((cur - prev) / prev) * 100;
      })()
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Dashboard <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
        <p className="text-sm text-gray-500">{new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</p>
      </div>

      {/* Available to Spend widget */}
      {ats && (
        <div className="card bg-gradient-to-br from-indigo-50 to-blue-50 border-indigo-100 dark:from-indigo-950/40 dark:to-blue-950/40 dark:border-indigo-900/50">
          <div className="flex items-center gap-2 mb-3">
            <Wallet size={16} className="text-indigo-500" />
            <h3 className="font-semibold text-gray-900 dark:text-white">
              Available to Spend —{" "}
              {new Date().toLocaleDateString("en-US", { month: "long" })}
            </h3>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between text-gray-600 dark:text-gray-400">
              <span>Monthly Income</span>
              <span className="tabular-nums text-green-600 dark:text-green-400 font-medium">{fmt(parseFloat(ats.monthly_income))}</span>
            </div>
            <div className="flex justify-between text-gray-600 dark:text-gray-400">
              <span>Committed Bills</span>
              <span className="tabular-nums text-red-500 dark:text-red-400 font-medium">−{fmt(parseFloat(ats.committed_expenses))}</span>
            </div>
            <div className="flex justify-between text-gray-600 dark:text-gray-400">
              <span>Spent So Far</span>
              <span className="tabular-nums text-amber-600 dark:text-amber-400 font-medium">−{fmt(parseFloat(ats.spent_this_month))}</span>
            </div>
            <div className="border-t border-gray-200 dark:border-gray-700 mt-2 pt-2 flex justify-between">
              <span className="font-semibold text-gray-900 dark:text-white">Available</span>
              <span className={`tabular-nums text-lg font-bold ${parseFloat(ats.available) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                {fmt(parseFloat(ats.available))}
              </span>
            </div>
          </div>
        </div>
      )}

      {weeklyDigest && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
            Weekly Digest — {new Date(weeklyDigest.week_start + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            {" – "}
            {new Date(weeklyDigest.week_end + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </h3>
          <p className="text-sm text-gray-500 mb-3">Total spent: <span className="font-semibold text-gray-900 dark:text-gray-100">{fmt(parseFloat(weeklyDigest.total_spent))}</span></p>

          {weeklyDigest.categories.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">By Category</p>
              <div className="space-y-1 text-sm">
                {weeklyDigest.categories.slice(0, 5).map((c: any) => (
                  <div key={c.category_id} className="flex justify-between text-gray-600 dark:text-gray-400">
                    <span>{c.category_name}</span>
                    <span className="tabular-nums">{fmt(parseFloat(c.total))}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {weeklyDigest.top_merchants.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Top Merchants</p>
              <div className="space-y-1 text-sm">
                {weeklyDigest.top_merchants.slice(0, 5).map((m: any) => (
                  <div key={m.name} className="flex justify-between text-gray-600 dark:text-gray-400">
                    <span>{m.name}</span>
                    <span className="tabular-nums">{fmt(parseFloat(m.total))}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {weeklyDigest?.risk && <RiskBanner risk={weeklyDigest.risk} />}

      {/* Month in Review */}
      {summary && (
        <div className="card">
          <div className="flex items-center gap-2 mb-2">
            <BookOpen size={16} className="text-indigo-500" />
            <h3 className="font-semibold text-gray-900 dark:text-white">
              Month in Review —{" "}
              {new Date(summaryYear, summaryMonth - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
            </h3>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{summary.text}</p>
          {summary.top_category && (
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-700 pt-3">
              <span>Top category: <span className="font-medium text-gray-700 dark:text-gray-300">{summary.top_category}</span></span>
              {summary.mom_delta_pct != null && (
                <span>
                  vs last month:{" "}
                  <span className={`font-medium ${parseFloat(summary.mom_delta_pct) > 0 ? "text-red-500" : "text-green-500"}`}>
                    {parseFloat(summary.mom_delta_pct) > 0 ? "+" : ""}{parseFloat(summary.mom_delta_pct).toFixed(1)}%
                  </span>
                </span>
              )}
              <span>
                Net cash flow:{" "}
                <span className={`font-medium ${parseFloat(summary.net_cashflow) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {fmt(Math.abs(parseFloat(summary.net_cashflow)))} {parseFloat(summary.net_cashflow) >= 0 ? "surplus" : "deficit"}
                </span>
              </span>
            </div>
          )}
        </div>
      )}

      {/* Hero stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="stat-card stat-card-accent-indigo animate-fade-slide-up animate-delay-100 col-span-2 sm:col-span-1">
          <span className="stat-label">Checking</span>
          <span className={`stat-value ${totalChecking >= 0 ? "text-gray-900" : "text-red-600"}`}>
            {anyBelowThreshold && <AlertTriangle size={18} className="text-amber-500 inline mr-1" />}
            {fmt(totalChecking)}
          </span>
          {nextPaycheck && (
            <span className="text-xs text-gray-500">
              Next paycheck: {nextPaycheck.next_date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            </span>
          )}
        </div>

        <div className="stat-card stat-card-accent-amber animate-fade-slide-up animate-delay-200">
          <span className="stat-label">Credit Card Balance</span>
          <span className="stat-value text-amber-600">{fmt(totalCards)}</span>
        </div>

        <div className="stat-card stat-card-accent-red animate-fade-slide-up animate-delay-300">
          <span className="stat-label">Amount Due</span>
          <span className={`stat-value ${totalCardsDue > 0 ? "text-red-600" : "text-gray-900"}`}>
            {fmt(totalCardsDue)}
          </span>
        </div>

        <div className={`stat-card animate-fade-slide-up animate-delay-400 ${totalChecking - totalCardsDue >= 0 ? "stat-card-accent-green" : "stat-card-accent-red"}`}>
          <span className="stat-label">Net Position</span>
          <span className={`stat-value ${totalChecking - totalCardsDue >= 0 ? "text-green-600" : "text-red-600"}`}>
            {fmt(totalChecking - totalCardsDue)}
          </span>
          <span className="text-xs text-gray-500">checking minus due</span>
          <div className="flex items-center justify-between mt-1">
            <TrendBadge pct={momPct} inverse />
            <SparkLine data={sparkData} color={totalChecking - totalCardsDue >= 0 ? "#22c55e" : "#ef4444"} />
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Credit cards */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2"><CreditCard size={16} /> Credit Cards</h3>
            <button onClick={() => navigate("/credit-cards")} className="text-xs text-indigo-600 hover:underline">Manage →</button>
          </div>
          {cards.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No credit cards added yet</p>
          ) : (
            <div className="space-y-3">
              {cards.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{c.name}</p>
                    <p className="text-xs text-gray-500">
                      {c.last_four && `••• ${c.last_four} · `}Due day {c.due_day}
                    </p>
                    <div className="mt-1 w-32">
                      <div className="progress-bar">
                        <div
                          className={`progress-fill ${utilBg(c.utilization_pct)}`}
                          style={{ width: `${Math.min(100, c.utilization_pct)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                  <div className="text-right shrink-0 ml-4">
                    <p className={`text-sm font-bold tabular-nums ${utilColor(c.utilization_pct)}`}>{fmt(c.current_balance)}</p>
                    <p className="text-xs text-gray-500">{c.utilization_pct}% of {fmt(c.credit_limit)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Upcoming bills */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2"><Calendar size={16} /> Upcoming Bills</h3>
            <button onClick={() => navigate("/recurring")} className="text-xs text-indigo-600 hover:underline">Manage →</button>
          </div>
          {upcoming.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No recurring bills set up</p>
          ) : (
            <div className="space-y-2">
              {upcoming.slice(0, 8).map((r: any) => {
                const daysUntil = Math.ceil((r.next_date.getTime() - todayDate.getTime()) / 86400000);
                return (
                  <div key={r.id} className="flex items-center justify-between py-1">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{r.name}</p>
                      <p className="text-xs text-gray-500">
                        {r.next_date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        {" · "}
                        <span className={daysUntil <= 3 ? "text-red-600 font-medium" : "text-gray-400"}>
                          {daysUntil === 0 ? "Today" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
                        </span>
                      </p>
                    </div>
                    <span className="text-sm font-semibold text-red-600 tabular-nums">{fmt(r.amount)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Accounts */}
      {accounts.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">All Accounts</h3>
          <div className="divide-y divide-gray-100">
            {accounts.map((a: any) => (
              <div key={a.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium text-gray-900">{a.name}</p>
                  <p className="text-xs text-gray-500 capitalize">{a.type.replace("_", " ")}</p>
                </div>
                <span className={`text-sm font-bold tabular-nums ${parseFloat(a.current_balance) >= 0 ? "text-gray-900" : "text-red-600"}`}>
                  {a.low_balance_threshold != null && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold) && (
                    <AlertTriangle size={14} className="text-amber-500 inline mr-1" />
                  )}
                  {fmt(a.current_balance)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state for new users */}
      {accounts.length === 0 && recurring.length === 0 && (
        <div className="card text-center py-10">
          <AlertCircle className="mx-auto text-indigo-300 mb-3" size={40} />
          <h3 className="font-semibold text-gray-700 mb-1">Welcome to OfflineBudget!</h3>
          <p className="text-sm text-gray-500 mb-4">Start by adding your checking account and recurring income/bills.</p>
          <div className="flex gap-3 justify-center">
            <button onClick={() => navigate("/settings")} className="btn-primary">Add Account</button>
            <button onClick={() => navigate("/recurring")} className="btn-secondary">Add Recurring Items</button>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Dashboard" body={DASHBOARD_HELP} onClose={() => setShowHelp(false)} />}
    </div>
  );
}
