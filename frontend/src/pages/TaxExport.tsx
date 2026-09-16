import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { spendingApi } from "../api";
import { api } from "../api/client";
import { fmt } from "../lib/utils";
import { AlertTriangle } from "lucide-react";

export default function TaxExport() {
  const [taxYear, setTaxYear] = useState(new Date().getFullYear() - 1);

  const { data: taxEstimate, isLoading: taxEstimateLoading } = useQuery({
    queryKey: ["tax-estimate", taxYear],
    queryFn: () => spendingApi.taxEstimate(taxYear),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-[#c4ccd8]">Tax Export</h2>
        <p className="text-sm text-gray-500 dark:text-[#8f99a8]">Estimated taxes and deductible-transaction export.</p>
      </div>

      <div className="space-y-4">
        {/* Year selector */}
        <div className="flex items-center gap-3">
          <label className="label mb-0">Tax Year</label>
          <select className="input w-auto" value={taxYear} onChange={e => setTaxYear(parseInt(e.target.value))}>
            {[-2, -1, 0].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
          </select>
          <button
            className="btn-secondary text-sm ml-auto"
            onClick={async () => {
              const res = await api.get(`/spending/tax-summary?year=${taxYear}&format=csv`, { responseType: "blob" });
              const url = URL.createObjectURL(res.data);
              const a = document.createElement("a");
              a.href = url;
              a.download = `tax-summary-${taxYear}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Download Deductibles CSV
          </button>
        </div>

        {taxEstimateLoading && <div className="text-center py-8 text-gray-400 text-sm">Calculating…</div>}

        {taxEstimate?.error && (
          <div className="card bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 text-sm">
            {taxEstimate.error} <a href="/settings/tax" className="underline ml-1">Go to Settings</a>
          </div>
        )}

        {taxEstimate && !taxEstimate.error && (() => {
          const te = taxEstimate as any;
          const refund = Number(te.total_refund_or_owed);
          const fedRefund = Number(te.federal_refund_or_owed);
          const stateRefund = Number(te.state_refund_or_owed);
          return (
            <div className="space-y-4">
              {/* Summary banner */}
              <div className={`card border-2 ${refund >= 0 ? "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/20" : "border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20"}`}>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{refund >= 0 ? "Estimated Refund" : "Estimated Amount Owed"}</p>
                    <p className={`text-3xl font-bold ${refund >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                      {refund >= 0 ? "+" : "-"}{fmt(Math.abs(refund))}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">Effective rate: {(Number(te.effective_rate) * 100).toFixed(1)}% · Filing: {te.filing_status.replace("_", " ")} · {te.state}</p>
                  </div>
                  <div className="text-sm space-y-1">
                    <div className="flex gap-6">
                      <span className="text-gray-500">Federal {fedRefund >= 0 ? "refund" : "owed"}</span>
                      <span className={`font-semibold ${fedRefund >= 0 ? "text-green-600" : "text-red-600"}`}>{fedRefund >= 0 ? "+" : ""}{fmt(fedRefund)}</span>
                    </div>
                    {!te.state_no_income_tax && (
                      <div className="flex gap-6">
                        <span className="text-gray-500">State {stateRefund >= 0 ? "refund" : "owed"}</span>
                        <span className={`font-semibold ${stateRefund >= 0 ? "text-green-600" : "text-red-600"}`}>{stateRefund >= 0 ? "+" : ""}{fmt(stateRefund)}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Breakdown */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="card space-y-2">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Income</h4>
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between"><dt className="text-gray-500">Gross salary</dt><dd className="tabular-nums">{fmt(Number(te.taxable_income) + Number(te.deduction_used))}</dd></div>
                    <div className="flex justify-between"><dt className="text-gray-500">Deduction ({te.used_itemized ? "itemized" : "standard"})</dt><dd className="tabular-nums text-green-600">−{fmt(te.deduction_used)}</dd></div>
                    <div className="flex justify-between border-t border-gray-100 dark:border-gray-700 pt-1 font-medium"><dt>Taxable income</dt><dd className="tabular-nums">{fmt(te.taxable_income)}</dd></div>
                    {te.used_itemized && te.itemized_breakdown && (() => {
                      const bd = te.itemized_breakdown;
                      const rows = [
                        { label: "Mortgage interest", val: bd.mortgage_interest },
                        { label: "Charitable donations", val: bd.donations },
                        { label: "SALT", val: bd.salt },
                        { label: "Property taxes", val: bd.property_tax },
                        { label: "Other deductions", val: bd.other },
                        { label: "Deductible transactions", val: bd.transaction_deductibles },
                      ].filter(r => r.val > 0);
                      return rows.map(r => (
                        <div key={r.label} className="flex justify-between text-xs text-gray-400 pl-2"><dt>{r.label}</dt><dd className="tabular-nums">{fmt(r.val)}</dd></div>
                      ));
                    })()}
                  </dl>
                </div>
                <div className="card space-y-2">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Tax Breakdown</h4>
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between"><dt className="text-gray-500">Federal income tax</dt><dd className="tabular-nums text-red-600">{fmt(te.federal_tax)}</dd></div>
                    {!te.state_no_income_tax && <div className="flex justify-between"><dt className="text-gray-500">State income tax ({(te.state_rate * 100).toFixed(2)}%)</dt><dd className="tabular-nums text-red-600">{fmt(te.state_tax)}</dd></div>}
                    {te.state_no_income_tax && <div className="flex justify-between"><dt className="text-gray-500">State income tax</dt><dd className="text-green-600 text-xs">No state income tax</dd></div>}
                    <div className="flex justify-between"><dt className="text-gray-500">Social Security (6.2%)</dt><dd className="tabular-nums text-red-600">{fmt(te.fica_ss)}</dd></div>
                    <div className="flex justify-between"><dt className="text-gray-500">Medicare (1.45%)</dt><dd className="tabular-nums text-red-600">{fmt(te.fica_medicare)}</dd></div>
                    <div className="flex justify-between border-t border-gray-100 dark:border-gray-700 pt-1 font-medium"><dt>Total taxes</dt><dd className="tabular-nums text-red-600">{fmt(te.total_tax)}</dd></div>
                  </dl>
                </div>
              </div>

              {/* Federal bracket ladder */}
              {te.brackets?.length > 0 && (
                <div className="card">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Federal Bracket Breakdown</h4>
                  <table className="w-full text-sm">
                    <thead><tr className="text-xs font-medium text-gray-500 uppercase">
                      <th className="pb-2 text-left">Rate</th>
                      <th className="pb-2 text-right">Income in bracket</th>
                      <th className="pb-2 text-right">Tax</th>
                    </tr></thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {(te.brackets as any[]).map((b: any, i: number) => (
                        <tr key={i}>
                          <td className="py-1 text-indigo-600 dark:text-indigo-300 font-medium">{(b.rate * 100).toFixed(0)}%</td>
                          <td className="py-1 text-right tabular-nums text-gray-600 dark:text-gray-400">{fmt(b.income)}</td>
                          <td className="py-1 text-right tabular-nums font-medium">{fmt(b.tax)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <>
                {(taxEstimate as any)?.bracket_year && (taxEstimate as any).bracket_year !== taxYear && (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 mb-2 dark:border-amber-900/60 dark:bg-amber-950/40">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                    <p className="text-xs text-amber-800 dark:text-amber-200">
                      You're estimating <b>{taxYear}</b>, but the bundled bracket tables are{" "}
                      <b>{(taxEstimate as any).bracket_year}</b>. Rates, bracket floors and the standard
                      deduction all shift year to year, so treat this as a rough figure until the {taxYear} tables ship.
                    </p>
                  </div>
                )}
                <p className="text-xs text-gray-400">
                  Estimates use {(taxEstimate as any)?.bracket_year ?? "bundled"} federal brackets. State tax uses
                  approximate effective rates. This is not tax advice — consult a tax professional.
                </p>
              </>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
