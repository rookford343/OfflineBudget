import { riskHasContent, type Risk } from "../lib/riskBannerText";
import { RiskBanner } from "./RiskBanner";
import { PlannedTransferReminder, usePlannedTransfersHasContent } from "./PlannedTransferReminder";
import BillsToConfirm, { useBillsToConfirmHasContent } from "./BillsToConfirm";
import AmountDrift, { useAmountDriftHasContent } from "./AmountDrift";

/**
 * One calm strip for everything on the Dashboard that wants an answer: the
 * forecast risk banner, planned transfers, bills to confirm, and amount drift.
 * With nothing pending it collapses to a single quiet line.
 */
export function NeedsAttention({ risk }: { risk: Risk | null | undefined }) {
  const transfers = usePlannedTransfersHasContent();
  const bills = useBillsToConfirmHasContent();
  const drift = useAmountDriftHasContent();
  const hasRisk = riskHasContent(risk);

  if (!hasRisk && !transfers && !bills && !drift) {
    return (
      <p className="text-sm text-muted bg-card border border-line rounded-xl px-4 py-3">
        Nothing needs you today.
      </p>
    );
  }

  return (
    <section aria-label="Needs attention" className="bg-card border border-line rounded-xl p-3 flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-ink px-1">Needs attention</h2>
      <RiskBanner risk={risk ?? undefined} />
      <PlannedTransferReminder />
      <BillsToConfirm />
      <AmountDrift />
    </section>
  );
}
