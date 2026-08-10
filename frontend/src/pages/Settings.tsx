import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { SlidersHorizontal, User, Link } from "lucide-react";
import { cx } from "../lib/utils";
import ProfileTab from "./settings/ProfileTab";
import PreferencesTab from "./settings/PreferencesTab";
import AccountsTab from "./settings/AccountsTab";

const TABS = [
  { to: "profile", label: "Profile & Security", icon: User },
  { to: "preferences", label: "Preferences", icon: SlidersHorizontal },
  { to: "accounts", label: "Accounts & Bank Sync", icon: Link },
];

export default function Settings() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Manage accounts, categories, and preferences</p>
      </div>
      <div className="flex flex-col md:flex-row gap-6">
        <nav className="md:w-48 shrink-0 flex md:flex-col gap-1 overflow-x-auto">
          {TABS.map(t => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap",
                  isActive
                    ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
                    : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                )
              }
            >
              <t.icon size={16} />
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1 min-w-0">
          <Routes>
            <Route index element={<Navigate to="profile" replace />} />
            <Route path="profile" element={<ProfileTab />} />
            <Route path="preferences" element={<PreferencesTab />} />
            <Route path="accounts" element={<AccountsTab />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
