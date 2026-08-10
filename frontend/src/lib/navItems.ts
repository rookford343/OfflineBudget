import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard, CreditCard, TrendingUp, PieChart,
  Repeat, ArrowLeftRight, Target, Settings, Upload,
  CalendarDays, Wallet, BarChart2,
} from "lucide-react";

export interface NavItem {
  to: string;
  icon: LucideIcon;
  label: string;
}

export const DASHBOARD_ITEM: NavItem = { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" };
export const SETTINGS_ITEM: NavItem = { to: "/settings", icon: Settings, label: "Settings" };

export interface NavGroup {
  key: "overview" | "money" | "planning";
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    key: "overview", label: "Overview", items: [
      { to: "/net-worth", icon: BarChart2, label: "Net Worth" },
      { to: "/calendar", icon: CalendarDays, label: "Calendar" },
    ],
  },
  {
    key: "money", label: "Money", items: [
      { to: "/transactions", icon: ArrowLeftRight, label: "Transactions" },
      { to: "/spending", icon: PieChart, label: "Spending" },
      { to: "/recurring", icon: Repeat, label: "Recurring" },
      { to: "/import", icon: Upload, label: "Import" },
    ],
  },
  {
    key: "planning", label: "Planning", items: [
      { to: "/budget", icon: Target, label: "Budget" },
      { to: "/goals", icon: Wallet, label: "Goals" },
      { to: "/credit-cards", icon: CreditCard, label: "Credit Cards" },
      { to: "/forecast", icon: TrendingUp, label: "Forecast" },
    ],
  },
];

// Every item that CAN be pinned -- everything except Dashboard (always
// pinned, not a user choice) and Settings (always renders separately at
// the bottom of the sidebar, never grouped or pinnable).
export const PINNABLE_ITEMS: NavItem[] = NAV_GROUPS.flatMap(g => g.items);

export const PINNED_STORAGE_KEY = "pinnedNav";
const LEGACY_ORDER_STORAGE_KEY = "navOrder";

/** Reads the user's pinned nav items (`to` paths, Dashboard excluded --
 * it's always pinned and never stored). One-time migration: if the old
 * drag-order key still exists and the new key doesn't, seed pinnedNav from
 * its first 4 pinnable entries and delete the old key so this never runs
 * twice. */
export function loadPinnedNav(): string[] {
  try {
    const saved = localStorage.getItem(PINNED_STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch { /* fall through to migration/default */ }

  try {
    const legacy = localStorage.getItem(LEGACY_ORDER_STORAGE_KEY);
    if (legacy) {
      const order = JSON.parse(legacy) as string[];
      const pinnable = new Set(PINNABLE_ITEMS.map(i => i.to));
      const migrated = order.filter(to => pinnable.has(to)).slice(0, 4);
      localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(migrated));
      localStorage.removeItem(LEGACY_ORDER_STORAGE_KEY);
      return migrated;
    }
  } catch { /* fall through to empty default */ }

  return [];
}
