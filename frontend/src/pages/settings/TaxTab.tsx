import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../../api";

export default function TaxTab() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });

  const [taxFilingStatus, setTaxFilingStatus] = useState("single");
  const [taxState, setTaxState] = useState("");
  const [taxSalary, setTaxSalary] = useState("");
  const [taxOtherIncome, setTaxOtherIncome] = useState("");
  const [taxFedWithheld, setTaxFedWithheld] = useState("");
  const [taxStateWithheld, setTaxStateWithheld] = useState("");
  const [taxMortgageInterest, setTaxMortgageInterest] = useState("");
  const [taxDonations, setTaxDonations] = useState("");
  const [taxSalt, setTaxSalt] = useState("");
  const [taxPropertyTax, setTaxPropertyTax] = useState("");
  const [taxOther, setTaxOther] = useState("");
  const [taxSaved, setTaxSaved] = useState(false);
  const [ssGross, setSsGross] = useState("");
  const [ssWageBase, setSsWageBase] = useState("");
  const [ssBonus, setSsBonus] = useState("");

  const taxMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setTaxSaved(true); setTimeout(() => setTaxSaved(false), 2000); },
  });

  useEffect(() => {
    if (me) {
      setSsGross(me.ss_gross_per_paycheck ?? "");
      setSsWageBase(me.ss_wage_base ?? "176100");
      setSsBonus(me.ss_bonus_ytd ?? "");
      setTaxFilingStatus(me.tax_filing_status ?? "single");
      setTaxState(me.tax_state ?? "");
      setTaxSalary(me.annual_salary ?? "");
      setTaxOtherIncome(me.other_income ?? "");
      setTaxFedWithheld(me.federal_withholding_ytd ?? "");
      setTaxStateWithheld(me.state_withholding_ytd ?? "");
      setTaxMortgageInterest(me.itemized_mortgage_interest ?? "");
      setTaxDonations(me.itemized_donations ?? "");
      setTaxSalt(me.itemized_salt ?? "");
      setTaxPropertyTax(me.itemized_property_tax ?? "");
      setTaxOther(me.itemized_other ?? "");
    }
  }, [me]);

  return (
    <div className="card">
      <div className="space-y-3">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">Tax Profile</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400">Used to estimate your tax obligation in the Spending → Tax tab. All values are estimates — consult a tax professional.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
          <div>
            <label className="label">Filing Status</label>
            <select className="input" value={taxFilingStatus} onChange={e => setTaxFilingStatus(e.target.value)}>
              <option value="single">Single</option>
              <option value="married_jointly">Married Filing Jointly</option>
              <option value="married_separately">Married Filing Separately</option>
              <option value="head_of_household">Head of Household</option>
            </select>
          </div>
          <div>
            <label className="label">State (2-letter code)</label>
            <input className="input uppercase" placeholder="e.g. TX" maxLength={2} value={taxState} onChange={e => setTaxState(e.target.value.toUpperCase())} />
          </div>
          <div>
            <label className="label">Annual Gross Salary (W-2)</label>
            <input type="number" step="1" className="input" placeholder="e.g. 85000" value={taxSalary} onChange={e => setTaxSalary(e.target.value)} />
          </div>
          <div>
            <label className="label">Other Income (1099, dividends, etc.)</label>
            <input type="number" step="1" className="input" placeholder="e.g. 5000" value={taxOtherIncome} onChange={e => setTaxOtherIncome(e.target.value)} />
          </div>
          <div>
            <label className="label">Federal Tax Withheld YTD</label>
            <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxFedWithheld} onChange={e => setTaxFedWithheld(e.target.value)} />
          </div>
          <div>
            <label className="label">State Tax Withheld YTD</label>
            <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxStateWithheld} onChange={e => setTaxStateWithheld(e.target.value)} />
          </div>
        </div>
        <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Itemized Deductions (from tax documents)</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">These are added to any transactions marked tax-deductible. If the total exceeds the standard deduction, itemized will be used automatically.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
            <div>
              <label className="label">Mortgage Interest (Form 1098)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 35919.55" value={taxMortgageInterest} onChange={e => setTaxMortgageInterest(e.target.value)} />
            </div>
            <div>
              <label className="label">Charitable Donations</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 15600.00" value={taxDonations} onChange={e => setTaxDonations(e.target.value)} />
            </div>
            <div>
              <label className="label">State &amp; Local Taxes (SALT)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 10506.24" value={taxSalt} onChange={e => setTaxSalt(e.target.value)} />
            </div>
            <div>
              <label className="label">Property Taxes</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 6000.00" value={taxPropertyTax} onChange={e => setTaxPropertyTax(e.target.value)} />
            </div>
            <div>
              <label className="label">Other Deductions (vehicle tax, etc.)</label>
              <input type="number" step="0.01" className="input" placeholder="e.g. 713.00" value={taxOther} onChange={e => setTaxOther(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Social Security Tracker</p>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Track when you hit the SS wage base to plan for your resulting paycheck increase (~6.2% of gross). The 2025 wage base is $176,100.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
            <div>
              <label className="label">Gross Per Paycheck ($)</label>
              <input type="number" step="0.01" className="input" placeholder="5000" value={ssGross} onChange={e => setSsGross(e.target.value)} />
            </div>
            <div>
              <label className="label">SS Wage Base ($)</label>
              <input type="number" step="1" className="input" placeholder="176100" value={ssWageBase} onChange={e => setSsWageBase(e.target.value)} />
            </div>
            <div>
              <label className="label">YTD Bonus Subject to SS ($)</label>
              <input type="number" step="0.01" className="input" placeholder="0" value={ssBonus} onChange={e => setSsBonus(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            className="btn-primary text-sm"
            disabled={taxMut.isPending}
            onClick={() => taxMut.mutate({
              tax_filing_status: taxFilingStatus,
              tax_state: taxState || null,
              annual_salary: taxSalary ? parseFloat(taxSalary) : null,
              other_income: taxOtherIncome ? parseFloat(taxOtherIncome) : null,
              federal_withholding_ytd: taxFedWithheld ? parseFloat(taxFedWithheld) : null,
              state_withholding_ytd: taxStateWithheld ? parseFloat(taxStateWithheld) : null,
              itemized_mortgage_interest: taxMortgageInterest ? parseFloat(taxMortgageInterest) : null,
              itemized_donations: taxDonations ? parseFloat(taxDonations) : null,
              itemized_salt: taxSalt ? parseFloat(taxSalt) : null,
              itemized_property_tax: taxPropertyTax ? parseFloat(taxPropertyTax) : null,
              itemized_other: taxOther ? parseFloat(taxOther) : null,
              ss_gross_per_paycheck: ssGross ? parseFloat(ssGross) : null,
              ss_wage_base: ssWageBase ? parseFloat(ssWageBase) : null,
              ss_bonus_ytd: ssBonus ? parseFloat(ssBonus) : null,
            })}
          >
            {taxMut.isPending ? "Saving…" : "Save Tax Profile"}
          </button>
          {taxSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
      </div>
    </div>
  );
}
