import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { authApi } from "../../api";
import { getTheme, setTheme } from "../../store/theme";
import { Moon, Sun, Wand2 } from "lucide-react";
import { PINNABLE_ITEMS, loadPinnedNav, PINNED_STORAGE_KEY } from "../../lib/navItems";

export default function PreferencesTab() {
  const [dark, setDark] = useState(getTheme() === "dark");
  function toggleDark() { const next = !dark; setDark(next); setTheme(next); }

  // Seeded from the server so the displayed value matches the current
  // setting on load, same as the original Settings.tsx's shared `me` effect.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [transferIncrement, setTransferIncrement] = useState("");
  useEffect(() => { if (me) setTransferIncrement(me.transfer_increment ?? "1000"); }, [me]);
  const taxMut = useMutation({ mutationFn: authApi.updateMe });

  const [pinned, setPinned] = useState<string[]>(loadPinnedNav);
  function togglePin(to: string) {
    const next = pinned.includes(to) ? pinned.filter(t => t !== to) : [...pinned, to];
    setPinned(next);
    localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("nav-order-changed"));
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Preferences</h3>
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-3">
          {dark ? <Moon size={16} className="text-indigo-400" /> : <Sun size={16} className="text-amber-500" />}
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Dark Mode</span>
        </div>
        <button
          onClick={toggleDark}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${dark ? "bg-indigo-600" : "bg-gray-200"}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${dark ? "translate-x-6" : "translate-x-1"}`} />
        </button>
      </div>
      <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <Wand2 size={16} className="text-indigo-400" />
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Setup Wizard</span>
            <p className="text-xs text-gray-400">Add an account and income recurring item</p>
          </div>
        </div>
        <button
          onClick={() => window.dispatchEvent(new Event("open-wizard"))}
          className="btn-secondary text-sm px-3 py-1.5"
        >
          Open
        </button>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="mb-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Pinned Sidebar Items</span>
          <p className="text-xs text-gray-400">Dashboard is always pinned. Choose a few more for quick access above the grouped sections.</p>
        </div>
        <div className="space-y-1">
          {PINNABLE_ITEMS.map(item => (
            <label key={item.to} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 rounded accent-indigo-600"
                checked={pinned.includes(item.to)}
                onChange={() => togglePin(item.to)}
              />
              <item.icon size={14} className="text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">{item.label}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Suggested Transfer Increment</span>
            <p className="text-xs text-gray-400">Suggested transfers round up to this amount (e.g. $1,000 steps)</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              step="1"
              className="input w-28 text-sm text-right"
              value={transferIncrement}
              onChange={(e) => setTransferIncrement(e.target.value)}
            />
            <button
              onClick={() => taxMut.mutate({ transfer_increment: transferIncrement ? parseFloat(transferIncrement) : null })}
              disabled={taxMut.isPending}
              className="btn-secondary text-xs px-3 py-1.5"
            >
              {taxMut.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
