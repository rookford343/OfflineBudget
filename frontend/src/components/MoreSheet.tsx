import { useEffect, useRef } from "react";
import { NavLink } from "react-router-dom";
import { LogOut, Eye, EyeOff, Moon, Sun, X, Settings as SettingsIcon } from "lucide-react";
import { NAV_GROUPS, SETTINGS_ITEM } from "../lib/navItems";
import { cx } from "../lib/utils";

interface Props {
  onClose: () => void;
  onLogout: () => void;
  balancesHidden: boolean;
  onToggleBalances: () => void;
  isDark: boolean;
  onToggleTheme: () => void;
  badgeFor: (item: { badgeKey?: string }) => React.ReactNode;
}

/** Phone "More" bottom sheet: every page, Settings, display toggles, Log out. */
export default function MoreSheet({ onClose, onLogout, balancesHidden, onToggleBalances, isDark, onToggleTheme, badgeFor }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  // Focus the Close button on open; Escape closes. (Layout restores focus to
  // the More button once the sheet is gone.)
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const row = "flex min-h-[44px] items-center gap-3 rounded-lg px-3 text-sm text-ink hover:bg-surface";
  return (
    <div className="fixed inset-0 z-[60] lg:hidden" role="dialog" aria-modal="true" aria-label="More">
      <button aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-card px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl">
        <div className="flex items-center justify-between pb-2">
          <h2 className="text-base font-semibold text-ink">More</h2>
          <button ref={closeRef} onClick={onClose} aria-label="Close" className="flex h-11 w-11 items-center justify-center text-muted"><X size={20} /></button>
        </div>
        {NAV_GROUPS.map(group => (
          <div key={group.key} className="pb-2">
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{group.label}</p>
            {group.items.map(item => (
              <NavLink key={item.to} to={item.to} onClick={onClose}
                className={({ isActive }) => cx(row, isActive && "bg-surface text-accent")}>
                <item.icon size={18} />
                {item.label}
                {badgeFor(item)}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="border-t border-line pt-2">
          <NavLink to={SETTINGS_ITEM.to} onClick={onClose} className={row}>
            <SettingsIcon size={18} /> Settings
          </NavLink>
          <button onClick={onToggleBalances} className={cx(row, "w-full text-left")}>
            {balancesHidden ? <EyeOff size={18} /> : <Eye size={18} />}
            {balancesHidden ? "Show account balances" : "Hide account balances"}
          </button>
          <button onClick={onToggleTheme} className={cx(row, "w-full text-left")}>
            {isDark ? <Moon size={18} /> : <Sun size={18} />}
            {isDark ? "Switch to light mode" : "Switch to dark mode"}
          </button>
          <button onClick={() => { onClose(); onLogout(); }} className={cx(row, "w-full text-left text-red-600 dark:text-red-400")}>
            <LogOut size={18} /> Log out
          </button>
        </div>
      </div>
    </div>
  );
}
