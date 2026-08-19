import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clearAuth, getUser } from "../store/auth";
import { authApi, accountsApi } from "../api";
import QuickStartWizard from "./QuickStartWizard";
import { LogOut } from "lucide-react";
import { cx } from "../lib/utils";
import { DASHBOARD_ITEM, SETTINGS_ITEM, NAV_GROUPS, loadPinnedNav, PINNABLE_ITEMS } from "../lib/navItems";

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
  const [wizardOpen, setWizardOpen] = useState(false);
  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);

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

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="hidden md:flex w-60 flex-col bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 shrink-0">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h1 className="text-lg font-bold text-indigo-600">OfflineBudget</h1>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{me?.display_name ?? user?.display_name}</p>
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
        <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700">
          <button onClick={logout} className="nav-link w-full text-red-600 hover:bg-red-50 hover:text-red-700">
            <LogOut size={18} />
            Sign out
          </button>
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
