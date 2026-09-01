import * as Dialog from "@radix-ui/react-dialog";
import type { LucideIcon } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  icon?: LucideIcon;
  title: string;
  description: string;
  confirmLabel?: string;
  confirmingLabel?: string;
  onConfirm: () => void;
  isPending?: boolean;
  /** btn-danger (default) for destructive actions, btn-primary otherwise. */
  danger?: boolean;
}

// Built on Radix Dialog for real focus-trap/ESC/portal behavior instead of
// the hand-rolled `fixed inset-0` markup this exact confirm shape was
// copied from (CreditCards.tsx's delete-card modal) -- the visual
// convention (centered icon, bold title, gray description, flex-1 button
// pair) is preserved on purpose, only the chrome underneath changes.
export function ConfirmDialog({
  open, onOpenChange, icon: Icon, title, description,
  confirmLabel = "Confirm", confirmingLabel, onConfirm, isPending = false, danger = true,
}: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content
          className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <div className="card w-full max-w-sm text-center">
            {Icon && <Icon className={`mx-auto mb-3 ${danger ? "text-red-400" : "text-indigo-400"}`} size={32} aria-hidden="true" />}
            <Dialog.Title className="font-bold text-gray-900 mb-1">{title}</Dialog.Title>
            <Dialog.Description className="text-sm text-gray-500 mb-5">{description}</Dialog.Description>
            <div className="flex gap-3">
              <button
                onClick={onConfirm}
                disabled={isPending}
                className={`${danger ? "btn-danger" : "btn-primary"} flex-1`}
              >
                {isPending ? (confirmingLabel ?? `${confirmLabel}…`) : confirmLabel}
              </button>
              <Dialog.Close asChild>
                <button className="btn-secondary flex-1" disabled={isPending}>Cancel</button>
              </Dialog.Close>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
