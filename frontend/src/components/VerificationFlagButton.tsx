import { useState, useRef } from "react";
import { createPortal } from "react-dom";
import { Flag } from "lucide-react";
import { verificationFlagsApi } from "../api";
import { useParallelOpsEnabled } from "../store/parallelOps";

interface ExpectedField {
  key: string;
  label: string;
}

export function VerificationFlagButton({
  feature,
  referenceType,
  referenceId,
  observed,
  expectedFields,
  className = "",
}: {
  feature: "forecast" | "transactions" | "household_snapshot";
  referenceType?: string;
  referenceId?: number;
  observed: Record<string, unknown>;
  expectedFields: ExpectedField[];
  className?: string;
}) {
  const enabled = useParallelOpsEnabled();
  const [open, setOpen] = useState(false);
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!enabled) return null;

  function toggle() {
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      // Popover is w-64 (256px); right-align it under the trigger, clamped so it
      // never renders off the left edge of the viewport.
      setPopoverPos({ top: rect.bottom + 4, left: Math.max(8, rect.right - 256) });
    }
    setError(null);
    setOpen((o) => !o);
  }

  async function submit() {
    const filled = expectedFields.filter((f) => values[f.key]?.trim());
    if (filled.length === 0 && !note.trim()) return;
    setSubmitting(true);
    setError(null);
    let succeeded = 0;
    try {
      const submissions = filled.length > 0 ? filled : [null];
      for (const field of submissions) {
        await verificationFlagsApi.create({
          feature,
          reference_type: referenceType,
          reference_id: referenceId,
          observed: field ? { ...observed, flagged_field: field.key } : observed,
          expected_value: field ? parseFloat(values[field.key]) : undefined,
          note: note.trim() || undefined,
        });
        succeeded++;
      }
      setDone(true);
      setValues({});
      setNote("");
      setTimeout(() => {
        setDone(false);
        setOpen(false);
      }, 1500);
    } catch {
      const total = filled.length > 0 ? filled.length : 1;
      setError(succeeded > 0 ? `Saved ${succeeded} of ${total} — try again for the rest` : "Couldn't save — try again");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={`relative inline-block ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        title="Flag this as wrong"
        className="text-gray-300 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400"
      >
        <Flag size={14} />
      </button>
      {open &&
        popoverPos &&
        createPortal(
          <div
            style={{ position: "fixed", top: popoverPos.top, left: popoverPos.left }}
            className="z-50 w-64 card p-3 shadow-lg text-left"
          >
            {done ? (
              <p className="text-sm text-emerald-600 dark:text-emerald-400">Flagged — thanks, I'll look into it.</p>
            ) : (
              <>
                <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">What should this be?</p>
                {expectedFields.map((f) => (
                  <label key={f.key} className="block mb-2 text-xs text-gray-500 dark:text-gray-400">
                    {f.label}
                    <input
                      type="number"
                      step="0.01"
                      className="input w-full text-sm mt-0.5"
                      value={values[f.key] ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  </label>
                ))}
                <label className="block mb-2 text-xs text-gray-500 dark:text-gray-400">
                  Note
                  <textarea
                    className="input w-full text-sm mt-0.5"
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                {error && <p className="text-xs text-red-500 mb-2">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setOpen(false)} className="btn-secondary text-xs px-2 py-1">
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={submit}
                    disabled={submitting}
                    className="btn-primary text-xs px-2 py-1 disabled:opacity-50"
                  >
                    {submitting ? "Saving…" : "Flag it"}
                  </button>
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
