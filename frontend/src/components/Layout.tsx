import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clearAuth, getUser } from "../store/auth";
import { authApi, accountsApi } from "../api";
import QuickStartWizard from "./QuickStartWizard";
import {
  LayoutDashboard, CreditCard, TrendingUp, PieChart,
  Repeat, ArrowLeftRight, Target, Settings, LogOut, Upload,
  CalendarDays, Wallet, BarChart2,
} from "lucide-react";
import { cx } from "../lib/utils";

const nav = [
  { to: "/dashboard",    icon: LayoutDashboard, label: "Dashboard"      },
  { to: "/goals",        icon: Wallet,           label: "Goals"          },
  { to: "/net-worth",   icon: BarChart2,         label: "Net Worth"      },
  { to: "/calendar",     icon: CalendarDays,     label: "Calendar"       },
  { to: "/credit-cards", icon: CreditCard,       label: "Credit Cards"   },
  { to: "/forecast",     icon: TrendingUp,        label: "Forecast"       },
  { to: "/spending",     icon: PieChart,          label: "Spending"       },
  { to: "/recurring",    icon: Repeat,            label: "Recurring"      },
  { to: "/transactions", icon: ArrowLeftRight,    label: "Transactions"   },
  { to: "/import",       icon: Upload,            label: "Import"         },
  { to: "/budget",       icon: Target,            label: "Budget"         },
  { to: "/settings",     icon: Settings,          label: "Settings"       },
];

function loadOrderedNav() {
  try {
    const saved = localStorage.getItem("navOrder");
    if (!saved) return nav;
    const order = JSON.parse(saved) as string[];
    const sorted = order.map(to => nav.find(n => n.to === to)!).filter(Boolean);
    const seen = new Set(order);
    const remaining = nav.filter(n => !seen.has(n.to));
    return [...sorted, ...remaining];
  } catch { return nav; }
}

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
  const [orderedNav, setOrderedNav] = useState(loadOrderedNav);

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
    const handler = () => setOrderedNav(loadOrderedNav());
    window.addEventListener("nav-order-changed", handler);
    return () => window.removeEventListener("nav-order-changed", handler);
  }, []);

  const showWizard = wizardOpen;

  function logout() {
    clearAuth();
    navigate("/login");
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
          {orderedNav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => cx(isActive ? "nav-link-active" : "nav-link")}
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
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
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
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
        {orderedNav.slice(0, 5).map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cx("flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg text-xs font-medium",
                isActive ? "text-indigo-600" : "text-gray-500")
            }
          >
            <Icon size={20} />
            <span>{label.split(" ")[0]}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
