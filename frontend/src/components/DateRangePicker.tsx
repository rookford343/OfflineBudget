import { useState, useRef, useEffect } from "react";
import { Calendar, ChevronDown } from "lucide-react";
import { quickRange, type QuickRangePreset } from "../lib/utils";

interface DateRangePickerProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}

const PRESETS: [string, QuickRangePreset][] = [
  ["This Month", "month"],
  ["Last 3 Months", "3months"],
  ["Year to Date", "ytd"],
  ["Last Year", "lastyear"],
];

function fmtRangeLabel(start: string, end: string): string {
  const s = new Date(start + "T12:00:00");
  const e = new Date(end + "T12:00:00");
  const sameYear = s.getFullYear() === e.getFullYear();
  const sameMonth = sameYear && s.getMonth() === e.getMonth();
  // A range that's exactly one calendar month reads as "August 2026"
  // instead of "Aug 1 - Aug 31, 2026" -- matches how the quick-range
  // presets and the rest of the app already talk about months.
  const isFullMonth =
    sameMonth &&
    s.getDate() === 1 &&
    e.getDate() === new Date(e.getFullYear(), e.getMonth() + 1, 0).getDate();
  if (isFullMonth) {
    return s.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  }
  const startFmt = s.toLocaleDateString("en-US", { month: "short", day: "numeric", year: sameYear ? undefined : "numeric" });
  const endFmt = e.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return `${startFmt} – ${endFmt}`;
}

// Reusable popover-style date-range picker replacing raw <input type="date">
// pairs -- same visual language (pill trigger, floating card, click-outside
// to close) as MonthYearPicker, extended to a start/end range instead of a
// single month.
export default function DateRangePicker({ start, end, onChange }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [draftStart, setDraftStart] = useState(start);
  const [draftEnd, setDraftEnd] = useState(end);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraftStart(start);
    setDraftEnd(end);
  }, [start, end]);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function pickPreset(preset: QuickRangePreset) {
    const r = quickRange(preset);
    onChange(r.start, r.end);
    setOpen(false);
  }

  function applyCustom() {
    if (draftStart && draftEnd) {
      onChange(draftStart, draftEnd);
      setOpen(false);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700"
      >
        <Calendar size={14} className="text-gray-400" />
        {fmtRangeLabel(start, end)}
        <ChevronDown size={14} className="text-gray-400" />
      </button>

      {open && (
        <div className="absolute top-full mt-2 right-0 z-20 w-72 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#2a2f3d] shadow-lg p-4">
          <div className="grid grid-cols-2 gap-1.5 mb-3">
            {PRESETS.map(([label, preset]) => (
              <button
                key={preset}
                onClick={() => pickPreset(preset)}
                className="px-2 py-1.5 text-xs font-medium rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400"
              >
                {label}
              </button>
            ))}
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-3 space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 dark:text-gray-400 w-10 shrink-0">From</label>
              <input type="date" className="input py-1 text-sm" value={draftStart} onChange={e => setDraftStart(e.target.value)} />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 dark:text-gray-400 w-10 shrink-0">To</label>
              <input type="date" className="input py-1 text-sm" value={draftEnd} onChange={e => setDraftEnd(e.target.value)} />
            </div>
            <button
              onClick={applyCustom}
              disabled={!draftStart || !draftEnd}
              className="btn-primary w-full text-sm py-1.5 mt-1"
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
