import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../api";
import { fmt, fmtDate } from "../lib/utils";

type Basis = "projected" | "projected_full_year" | "past_year" | "ytd_only";
type Breakdown = { basis: Basis; ytd: number; per_paycheck: number; remaining_paychecks: number; bonus: number; total: number };

function WithholdingRows({ label, w, te }: { label: string; w: Breakdown; te: any }) {
  // Each tax has its own basis: one can project while the other, with a
  // blank this-period amount, stays on its YTD figure.
  const basis = w.basis ?? te.withholding_basis;
  const asOf = te.withholding_as_of;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-gray-600 dark:text-gray-400">{label}</p>
      <dl className="space-y-1 text-sm">
        {(basis === "projected" || basis === "ytd_only") && (
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Year to date{asOf ? ` (as of ${fmtDate(asOf)})` : ""}</dt>
            <dd className="tabular-nums">{fmt(w.ytd)}</dd>
          </div>
        )}
        {(basis === "projected" || basis === "projected_full_year") && (
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">
              {te.paychecks_remaining} {basis === "projected" ? "remaining " : ""}paycheck{te.paychecks_remaining === 1 ? "" : "s"} × {fmt(w.per_paycheck)}
            </dt>
            <dd className="tabular-nums">{fmt(w.remaining_paychecks)}</dd>
          </div>
        )}
        {Number(w.bonus) > 0 && (
          <div className="flex justify-between gap-2">
            <dt className="text-gray-500">Bonus withholding</dt>
            <dd className="tabular-nums">{fmt(w.bonus)}</dd>
          </div>
        )}
        <div className="flex justify-between gap-2 border-t border-gray-100 dark:border-gray-700 pt-1 font-medium">
          <dt>{basis === "ytd_only" ? "Withheld so far" : "Projected for the year"}</dt>
          <dd className="tabular-nums">{fmt(w.total)}</dd>
        </div>
      </dl>
    </div>
  );
}

/** How the withholding compared against the estimated tax was found. */
export function WithholdingCard({ te, taxYear }: { te: any; taxYear: number }) {
  const basis = te.withholding_basis;
  // The taxes shown, with their own bases (top-level basis is "mixed" when they differ).
  const shown: { label: string; w: Breakdown }[] = [{ label: "Federal", w: te.withholding.federal }];
  if (!te.state_no_income_tax) shown.push({ label: "State", w: te.withholding.state });
  const basisOf = (w: Breakdown) => w.basis ?? basis;
  const ytdOnly = shown.filter(t => basisOf(t.w) === "ytd_only").map(t => t.label);
  const anyBasis = (b: Basis) => shown.some(t => basisOf(t.w) === b);
  return (
    <div className="card space-y-3">
      <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Withholding</h4>
      {basis === "past_year" ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Your pay stub is from a later year, so there's nothing to project for {taxYear}. Compare with your W-2.
        </p>
      ) : (
        <>
          {shown.map(t => <WithholdingRows key={t.label} label={t.label} w={t.w} te={te} />)}
        </>
      )}
      {basis !== "past_year" && ytdOnly.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {ytdOnly.length === shown.length
            ? <>Only year-to-date withholding is counted, so the result leans toward owing. Fill in
              "From your latest pay stub" to project the rest of the year.</>
            : <>{ytdOnly.join(" and ")} counts only year-to-date withholding, so the result leans toward
              owing. Fill in "{ytdOnly.join(" and ")} withheld this period" to project the rest of the year.</>}
        </p>
      )}
      {anyBasis("projected_full_year") && (
        <p className="text-xs text-gray-400">
          No {taxYear} pay stub yet, so a full year of paychecks at your latest per-paycheck withholding is assumed.
        </p>
      )}
      {Number(te.bonus_gross) > 0 && (anyBasis("projected") || anyBasis("projected_full_year")) && (
        <p className="text-xs text-gray-400">Bonuses not yet paid are withheld at 22% federal plus your state rate.</p>
      )}
      {te.paycheck_basis === "assumed_biweekly" && basis !== "past_year" && (
        <p className="text-xs text-gray-400">
          No paycheck found on your recurring schedule (it's matched against Gross Per Paycheck in
          Settings → Tax), so 26 paychecks a year are assumed.
        </p>
      )}
    </div>
  );
}

const num = (v: string) => (v ? parseFloat(v) : null);

/** Pay-stub inputs that drive the withholding projection. */
export default function PayStubCard() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [asOf, setAsOf] = useState("");
  const [fedYtd, setFedYtd] = useState("");
  const [stateYtd, setStateYtd] = useState("");
  const [fedPer, setFedPer] = useState("");
  const [statePer, setStatePer] = useState("");
  const [pretax, setPretax] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (me) {
      setAsOf(me.tax_withholding_as_of ?? "");
      setFedYtd(me.federal_withholding_ytd ?? "");
      setStateYtd(me.state_withholding_ytd ?? "");
      setFedPer(me.federal_withheld_per_paycheck ?? "");
      setStatePer(me.state_withheld_per_paycheck ?? "");
      setPretax(me.pretax_per_paycheck ?? "");
    }
  }, [me]);

  const mut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["tax-estimate"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <div className="card space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">From your latest pay stub</h4>
        <p className="text-xs text-gray-400 mt-0.5">Used to project the full year's withholding.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2">
          <label className="label">Pay date</label>
          <input type="date" className="input" value={asOf} onChange={e => setAsOf(e.target.value)} />
        </div>
        <div>
          <label className="label">Federal withheld YTD</label>
          <input type="number" step="0.01" className="input" placeholder="0.00" value={fedYtd} onChange={e => setFedYtd(e.target.value)} />
        </div>
        <div>
          <label className="label">State withheld YTD</label>
          <input type="number" step="0.01" className="input" placeholder="0.00" value={stateYtd} onChange={e => setStateYtd(e.target.value)} />
        </div>
        <div>
          <label className="label">Federal withheld this period</label>
          <input type="number" step="0.01" className="input" placeholder="0.00" value={fedPer} onChange={e => setFedPer(e.target.value)} />
        </div>
        <div>
          <label className="label">State withheld this period</label>
          <input type="number" step="0.01" className="input" placeholder="0.00" value={statePer} onChange={e => setStatePer(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label className="label">Pre-tax deductions per paycheck</label>
          <input type="number" step="0.01" className="input" placeholder="0.00" value={pretax} onChange={e => setPretax(e.target.value)} />
          <p className="text-xs text-gray-400 mt-1">
            401k, HSA, medical/dental premiums. Lowers federal and state taxable wages; Social Security and
            Medicare are still figured on full pay, which is the conservative choice.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button
          className="btn-primary text-sm"
          disabled={mut.isPending}
          onClick={() => mut.mutate({
            tax_withholding_as_of: asOf || null,
            federal_withholding_ytd: num(fedYtd),
            state_withholding_ytd: num(stateYtd),
            federal_withheld_per_paycheck: num(fedPer),
            state_withheld_per_paycheck: num(statePer),
            pretax_per_paycheck: num(pretax),
          })}
        >
          {mut.isPending ? "Saving…" : "Save"}
        </button>
        {saved && <span className="text-sm text-green-600">Saved!</span>}
        {mut.isError && <span className="text-sm text-red-600">Couldn't save. Try again.</span>}
      </div>
    </div>
  );
}
