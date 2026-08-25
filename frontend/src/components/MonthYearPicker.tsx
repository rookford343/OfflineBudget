import { useState, useRef, useEffect } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { cx } from "../lib/utils";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface MonthYearPickerProps {
  year: number;
  month: number; // 1-12
  onChange: (year: number, month: number) => void;
}

export default function MonthYearPicker({ year, month, onChange }: MonthYearPickerProps) {
  const [open, setOpen] = useState(false);
  const [popoverYear, setPopoverYear] = useState(year);
  const rootRef = useRef<HTMLDivElement>(null);

  // Keep the popover's year stepper in sync if the caller changes `year`
  // out from under us (e.g. the arrow buttons), so re-opening the popover
  // doesn't show a stale year.
  useEffect(() => {
    setPopoverYear(year);
  }, [year]);

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

  function prevMonth() {
    if (month === 1) onChange(year - 1, 12);
    else onChange(year, month - 1);
  }

  function nextMonth() {
    if (month === 12) onChange(year + 1, 1);
    else onChange(year, month + 1);
  }

  function pickMonth(m: number) {
    onChange(popoverYear, m);
    setOpen(false);
  }

  return (
    <div ref={rootRef} className="relative flex items-center gap-1">
      <button
        onClick={prevMonth}
        className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
        aria-label="Previous month"
      >
        <ChevronLeft size={16} />
      </button>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700"
      >
        <Calendar size={14} />
        {MONTHS[month - 1]} {year}
      </button>
      <button
        onClick={nextMonth}
        className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
        aria-label="Next month"
      >
        <ChevronRight size={16} />
      </button>

      {open && (
        <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 z-20 w-64 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <button
              onClick={() => setPopoverYear(y => y - 1)}
              className="p-1 rounded-full text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              aria-label="Previous year"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="font-semibold text-gray-900 dark:text-gray-100">{popoverYear}</span>
            <button
              onClick={() => setPopoverYear(y => y + 1)}
              className="p-1 rounded-full text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              aria-label="Next year"
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {MONTHS.map((m, i) => {
              const isSelected = popoverYear === year && i + 1 === month;
              return (
                <button
                  key={m}
                  onClick={() => pickMonth(i + 1)}
                  className={cx(
                    "py-2 rounded-lg text-sm font-medium",
                    isSelected
                      ? "bg-indigo-600 text-white"
                      : "text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  )}
                >
                  {m}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
