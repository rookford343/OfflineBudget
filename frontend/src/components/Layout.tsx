import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clearAuth, getUser } from "../store/auth";
import { authApi, accountsApi, transactionsApi } from "../api";
import QuickStartWizard from "./QuickStartWizard";
import { TrendBadge } from "./TrendBadge";
import { LogOut, Eye, EyeOff, Moon, Sun, ChevronDown, ChevronsUpDown, KeyRound } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { cx, fmt, firstOfMonth } from "../lib/utils";
import { DASHBOARD_ITEM, SETTINGS_ITEM, NAV_GROUPS, loadPinnedNav, PINNABLE_ITEMS } from "../lib/navItems";
import { useBalancesHidden, toggleBalancesHidden, maskIfHidden } from "../store/balanceVisibility";
import { useIsDarkMode, toggleTheme } from "../store/theme";

export default function Layout() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = getUser();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me, staleTime: 60_000 });
  const { data: accounts = [], isSuccess: accountsLoaded } = useQuery({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
    staleTime: 30_000,
  });
  // This month's transactions, fetched once and grouped per-account below --
  // there's no stored per-account balance history, so "% change" is derived
  // from actual transaction flow (net this-month flow ÷ start-of-month
  // balance) rather than a number with no real basis behind it.
  const { data: monthTxns = [] } = useQuery({
    queryKey: ["transactions", { start: firstOfMonth() }],
    queryFn: () => transactionsApi.list({ start: firstOfMonth() }),
    staleTime: 30_000,
  });
  const [wizardOpen, setWizardOpen] = useState(false);
  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);
  const [accountsExpanded, setAccountsExpanded] = useState(false);
  const balancesHidden = useBalancesHidden();
  const isDark = useIsDarkMode();

  // Latch open once on first load if no accounts exist — don't re-derive from live query
  // so the wizard stays visible after step 1 creates the first account.
  useEffect(() => {
    if (accountsLoaded && (accounts as any[]).length === 0) {
      setWizardOpen(true);
    }
  }, [accountsLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Allow Settings (or any page) to open the wizard via a custom event.
  useEffect(() => {
    const handler = () => setWizardOpen(true);
    window.addEventListener("open-wizard", handler);
    return () => window.removeEventListener("open-wizard", handler);
  }, []);

  useEffect(() => {
    const handler = () => setPinned(loadPinnedNav());
    window.addEventListener("nav-order-changed", handler);
    return () => window.removeEventListener("nav-order-changed", handler);
  }, []);

  const showWizard = wizardOpen;
  const pinnedSet = new Set(pinned);
  // Render pinned items in PINNABLE_ITEMS' fixed order, not the order the user
  // happened to tick the checkboxes in. Filtering PINNABLE_ITEMS by membership
  // preserves that order for free and can't yield a miss to filter out.
  const pinnedItems = PINNABLE_ITEMS.filter(item => pinnedSet.has(item.to));
  // The sidebar is `hidden md:flex`, so below md this bottom bar is the ONLY
  // navigation. With no pins it must still offer real destinations, and
  // Settings must always survive the cap since it's the only route to the pin
  // picker. Slicing the middle to 3 (rather than the whole array to 5) reserves
  // the last slot for Settings no matter how many items are pinned.
  const middleItems = pinnedItems.length > 0 ? pinnedItems : PINNABLE_ITEMS.slice(0, 3);
  const mobileItems = [DASHBOARD_ITEM, ...middleItems.slice(0, 3), SETTINGS_ITEM];

  function logout() {
    clearAuth();
    navigate("/login");
  }

  function navLinkClass({ isActive }: { isActive: boolean }) {
    return cx(isActive ? "nav-link-active" : "nav-link");
  }

  // Emergency-fund accounts (Money Market) sort last -- they're not part of
  // day-to-day spending, so they belong at the bottom of the list, not
  // wherever alphabetical type ordering happens to land them.
  const sortedAccounts = [...(accounts as any[])].sort((a, b) => {
    if (!!a.is_emergency_fund !== !!b.is_emergency_fund) return a.is_emergency_fund ? 1 : -1;
    return a.type.localeCompare(b.type) || a.name.localeCompare(b.name);
  });
  const totalAccountBalance = sortedAccounts.reduce((sum, a: any) => sum + parseFloat(a.current_balance), 0);

  // Net flow this month per account, from the transactions query above.
  const flowByAccount: Record<number, number> = {};
  (monthTxns as any[]).forEach(t => {
    flowByAccount[t.account_id] = (flowByAccount[t.account_id] ?? 0) + parseFloat(t.amount);
  });

  // % change = this month's net flow over the balance before it. Null when
  // the start-of-month balance is too close to zero for a percentage to be
  // meaningful (avoids a wild or divide-by-near-zero number).
  function pctChangeFor(a: any): number | null {
    const flow = flowByAccount[a.id] ?? 0;
    const startBalance = parseFloat(a.current_balance) - flow;
    if (Math.abs(startBalance) < 0.01) return null;
    return (flow / startBalance) * 100;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="hidden md:flex w-60 flex-col bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 shrink-0">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold text-indigo-600">OfflineBudget</h1>
            <div className="flex items-center gap-2">
              <button
                onClick={toggleTheme}
                className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                title={isDark ? "Switch to light mode" : "Switch to dark mode"}
                aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
              >
                {isDark ? <Moon size={16} /> : <Sun size={16} />}
              </button>
              <button
                onClick={toggleBalancesHidden}
                className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                title={balancesHidden ? "Show account balances" : "Hide account balances"}
                aria-label={balancesHidden ? "Show account balances" : "Hide account balances"}
              >
                {balancesHidden ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <NavLink to={DASHBOARD_ITEM.to} className={navLinkClass}>
            <DASHBOARD_ITEM.icon size={18} />
            {DASHBOARD_ITEM.label}
          </NavLink>
          {pinnedItems.map(item => (
            <NavLink key={item.to} to={item.to} className={navLinkClass}>
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
          {pinnedItems.length > 0 && <div className="my-2 border-t border-gray-100 dark:border-gray-700" />}
          {NAV_GROUPS.map(group => {
            const visible = group.items.filter(i => !pinnedSet.has(i.to));
            if (visible.length === 0) return null;
            return (
              <div key={group.key} className="pt-3 first:pt-0">
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-400">{group.label}</p>
                {visible.map(item => (
                  <NavLink key={item.to} to={item.to} className={navLinkClass}>
                    <item.icon size={18} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
          <div className="my-2 border-t border-gray-100 dark:border-gray-700" />
          <NavLink to={SETTINGS_ITEM.to} className={navLinkClass}>
            <SETTINGS_ITEM.icon size={18} />
            {SETTINGS_ITEM.label}
          </NavLink>
        </nav>
        {sortedAccounts.length > 0 && (
          <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between px-2 pb-1 gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-400 shrink-0">
                Accounts
              </p>
              <span className="text-xs font-semibold tabular-nums text-gray-500 dark:text-gray-400 truncate">
                {maskIfHidden(balancesHidden, fmt(totalAccountBalance))}
              </span>
              {sortedAccounts.length > 4 && (
                <button
                  onClick={() => setAccountsExpanded(e => !e)}
                  className="shrink-0 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                  title={accountsExpanded ? "Show fewer accounts" : "Show all accounts"}
                  aria-label={accountsExpanded ? "Show fewer accounts" : "Show all accounts"}
                >
                  <ChevronDown size={14} className={cx("transition-transform", accountsExpanded && "rotate-180")} />
                </button>
              )}
            </div>
            <ul className="space-y-0.5">
              {(accountsExpanded ? sortedAccounts : sortedAccounts.slice(0, 4)).map((a: any) => {
                const pct = pctChangeFor(a);
                return (
                  <li key={a.id}>
                    <NavLink
                      to={`/accounts/${a.id}`}
                      className={({ isActive }) =>
                        cx(
                          "flex items-center justify-between px-2 py-1.5 rounded-lg text-sm",
                          isActive ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300" : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                        )
                      }
                    >
                      <div className="min-w-0">
                        <p className="truncate">{a.name}</p>
                        <p className="text-xs text-gray-400 dark:text-gray-500 capitalize">{a.type.replace("_", " ")}</p>
                      </div>
                      {balancesHidden ? (
                        <span className="shrink-0 ml-2 text-gray-400 dark:text-gray-500">••••</span>
                      ) : (
                        <div className="shrink-0 ml-2 flex flex-col items-end gap-0.5">
                          <span className={`tabular-nums ${parseFloat(a.current_balance) < 0 ? "text-red-500 dark:text-red-400" : "text-gray-500 dark:text-gray-400"}`}>
                            {fmt(a.current_balance)}
                          </span>
                          {pct !== null && <TrendBadge pct={pct} />}
                        </div>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="w-full flex items-center justify-between px-2 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-700/40 hover:bg-gray-100 dark:hover:bg-gray-700/70 text-left">
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{me?.display_name ?? user?.display_name}</span>
                  {me?.email && <span className="block text-xs text-gray-400 dark:text-gray-500 truncate">{me.email}</span>}
                </span>
                <ChevronsUpDown size={14} className="shrink-0 ml-2 text-gray-400 dark:text-gray-500" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                side="top"
                align="start"
                sideOffset={6}
                className="w-52 rounded-xl bg-white dark:bg-[#2a2f3d] border border-gray-100 dark:border-[#3a4051] shadow-lg py-1.5 z-50"
              >
                <DropdownMenu.Item asChild>
                  <button onClick={() => navigate("/settings/profile")} className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 outline-none">
                    <KeyRound size={15} className="text-gray-400" />
                    Change Password
                  </button>
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="my-1.5 border-t border-gray-100 dark:border-gray-700" />
                <DropdownMenu.Item asChild>
                  <button onClick={logout} className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 outline-none">
                    <LogOut size={15} />
                    Sign out
                  </button>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
        {/* Fluid up to a readable ceiling. max-w-6xl (72rem) left most of a
            wide monitor empty, but an unbounded width stretches table rows and
            two-column cards until the eye has to travel across the whole
            display to pair a label with its value. */}
        <div className="w-full max-w-[120rem] mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <Outlet />
        </div>
      </main>

      {showWizard && (
        <QuickStartWizard
          onComplete={() => {
            qc.invalidateQueries({ queryKey: ["accounts"] });
            setWizardOpen(false);
          }}
          onDismiss={() => setWizardOpen(false)}
        />
      )}

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 flex justify-around px-2 py-2 z-50">
        {mobileItems.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cx("flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg text-xs font-medium",
                isActive ? "text-indigo-600" : "text-gray-500")
            }
          >
            <item.icon size={20} />
            <span>{item.label.split(" ")[0]}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
