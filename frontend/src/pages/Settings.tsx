import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { User, SlidersHorizontal, Link, Tags, Receipt, Users as UsersIcon, AlertTriangle, Flag, Bell } from "lucide-react";
import { cx } from "../lib/utils";
import ProfileTab from "./settings/ProfileTab";
import PreferencesTab from "./settings/PreferencesTab";
import AccountsTab from "./settings/AccountsTab";
import CategoriesTab from "./settings/CategoriesTab";
import TaxTab from "./settings/TaxTab";
import HouseholdTab from "./settings/HouseholdTab";
import DangerZoneTab from "./settings/DangerZoneTab";
import VerificationFeedbackTab from "./settings/VerificationFeedbackTab";
import NotificationsTab from "./settings/NotificationsTab";

// Absolute paths, not relative ("profile" instead of "/settings/profile") --
// these NavLinks sit next to a second, nested <Routes> inside a component
// mounted on a splat route (App.tsx's "settings/*"). A relative `to` there
// resolves against the splat's CURRENT matched value, not a fixed base, so
// each click appended another segment instead of replacing the last one
// (…/profile/preferences/accounts/… -- confirmed live, screenshot from
// production). Absolute paths sidestep the ambiguity entirely.
const TAB_GROUPS = [
  {
    label: "Profile",
    items: [
      { to: "/settings/profile", label: "Profile & Security", icon: User },
      { to: "/settings/preferences", label: "Preferences", icon: SlidersHorizontal },
      { to: "/settings/notifications", label: "Notifications & Email", icon: Bell },
    ],
  },
  {
    label: "Money",
    items: [
      { to: "/settings/accounts", label: "Accounts & Bank Sync", icon: Link },
      { to: "/settings/categories", label: "Categories & Rules", icon: Tags },
      { to: "/settings/tax", label: "Tax", icon: Receipt },
      { to: "/settings/household", label: "Household", icon: UsersIcon },
    ],
  },
  {
    label: "Data & Trust",
    items: [
      { to: "/settings/verification", label: "Verification Feedback", icon: Flag },
    ],
  },
  {
    label: "Danger Zone",
    items: [
      { to: "/settings/danger", label: "Danger Zone", icon: AlertTriangle, danger: true },
    ],
  },
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
          {TAB_GROUPS.map((group, gi) => (
            <div key={group.label} className={cx("flex md:flex-col gap-1", gi > 0 && "md:mt-3 md:pt-3 md:border-t md:border-gray-100 dark:md:border-gray-700")}>
              <p className="hidden md:block px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                {group.label}
              </p>
              {group.items.map(t => (
                <NavLink
                  key={t.to}
                  to={t.to}
                  className={({ isActive }) =>
                    cx(
                      "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap",
                      t.danger
                        ? (isActive ? "bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400" : "text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20")
                        : (isActive
                            ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300"
                            : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50")
                    )
                  }
                >
                  <t.icon size={16} />
                  {t.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="flex-1 min-w-0">
          <Routes>
            <Route index element={<Navigate to="/settings/profile" replace />} />
            <Route path="profile" element={<ProfileTab />} />
            <Route path="preferences" element={<PreferencesTab />} />
            <Route path="accounts" element={<AccountsTab />} />
            <Route path="notifications" element={<NotificationsTab />} />
            <Route path="categories" element={<CategoriesTab />} />
            <Route path="tax" element={<TaxTab />} />
            <Route path="household" element={<HouseholdTab />} />
            <Route path="danger" element={<DangerZoneTab />} />
            <Route path="verification" element={<VerificationFeedbackTab />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
