import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, recurringApi, cardsApi } from "../api";
import { CheckCircle, X } from "lucide-react";

interface Props {
  onComplete: () => void;
  onDismiss?: () => void;
}

export default function QuickStartWizard({ onComplete, onDismiss }: Props) {
  const qc = useQueryClient();
  const [step, setStep] = useState(1);
  const [createdAccountId, setCreatedAccountId] = useState<number | null>(null);

  const [accountName, setAccountName] = useState("Main Checking");
  const [accountBalance, setAccountBalance] = useState("0");

  const [incomeName, setIncomeName] = useState("Paycheck");
  const [incomeAmount, setIncomeAmount] = useState("");
  const [incomeDay, setIncomeDay] = useState("15");
  const [incomeFrequency, setIncomeFrequency] = useState<"monthly" | "semimonthly" | "biweekly" | "weekly">("monthly");

  const [cardName, setCardName] = useState("");
  const [cardLimit, setCardLimit] = useState("");
  const [cardStatementDay, setCardStatementDay] = useState("26");
  const [cardDueDay, setCardDueDay] = useState("23");

  const [error, setError] = useState<string | null>(null);

  const createAccountMut = useMutation({
    mutationFn: accountsApi.create,
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setCreatedAccountId(data.id);
      setError(null);
      setStep(2);
    },
    onError: (e: any) => setError(e?.response?.data?.detail ?? "Failed to create account"),
  });


  const createCardMut = useMutation({
    mutationFn: cardsApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      setError(null);
      setStep(4);
    },
    onError: (e: any) => setError(e?.response?.data?.detail ?? "Failed to add card"),
  });

  function submitAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!accountName.trim()) return;
    setError(null);
    createAccountMut.mutate({
      name: accountName.trim(),
      type: "checking",
      current_balance: parseFloat(accountBalance) || 0,
    });
  }

  function nextWeekday(d: Date): string {
    while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }

  async function submitIncome(e: React.FormEvent) {
    e.preventDefault();
    if (!createdAccountId || !incomeAmount) return;
    setError(null);
    const base = {
      type: "income",
      account_id: createdAccountId,
      start_date: new Date().toISOString().slice(0, 10),
    };
    const name = incomeName.trim() || "Paycheck";
    const amount = parseFloat(incomeAmount);
    try {
      if (incomeFrequency === "semimonthly") {
        await Promise.all([
          recurringApi.create({ ...base, name: `${name} (1st)`, amount, frequency: "monthly", day_of_month: 1 }),
          recurringApi.create({ ...base, name: `${name} (15th)`, amount, frequency: "monthly", day_of_month: 15 }),
        ]);
      } else if (incomeFrequency === "biweekly") {
        await recurringApi.create({ ...base, name, amount, frequency: "biweekly", day_of_month: 1, start_date: nextWeekday(new Date()) });
      } else if (incomeFrequency === "weekly") {
        await recurringApi.create({ ...base, name, amount, frequency: "weekly", day_of_month: 1, start_date: nextWeekday(new Date()) });
      } else {
        await recurringApi.create({ ...base, name, amount, frequency: "monthly", day_of_month: parseInt(incomeDay) || 15 });
      }
      qc.invalidateQueries({ queryKey: ["recurring"] });
      setStep(3);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Failed to create income");
    }
  }

  function skipIncome() {
    setStep(3);
  }

  function submitCard(e: React.FormEvent) {
    e.preventDefault();
    if (!cardName.trim() || !cardLimit) return;
    setError(null);
    createCardMut.mutate({
      name: cardName.trim(),
      credit_limit: parseFloat(cardLimit),
      statement_day: parseInt(cardStatementDay) || 26,
      due_day: parseInt(cardDueDay) || 23,
      current_balance: 0,
      balance_due: 0,
    });
  }

  function skipCard() {
    setStep(4);
  }

  const steps = [
    { n: 1, label: "Account" },
    { n: 2, label: "Income" },
    { n: 3, label: "Card" },
    { n: 4, label: "Done" },
  ];

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl p-8 w-full max-w-md shadow-2xl">
        <div className="flex items-start justify-between mb-1">
          <h1 className="text-lg font-bold text-indigo-600">OfflineBudget</h1>
          {onDismiss && (
            <button onClick={onDismiss} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 -mt-1 -mr-1 p-1">
              <X size={18} />
            </button>
          )}
        </div>
        <p className="text-xs text-gray-400 mb-6">Let's get you set up in a few quick steps.</p>

        {/* Step indicators */}
        <div className="flex items-center gap-2 mb-8">
          {steps.map((s, i) => (
            <div key={s.n} className="flex items-center gap-2 flex-1">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-colors ${
                step > s.n ? "bg-green-500 text-white" :
                step === s.n ? "bg-indigo-600 text-white" :
                "bg-gray-200 dark:bg-gray-600 text-gray-500 dark:text-gray-400"
              }`}>
                {step > s.n ? <CheckCircle size={14} /> : s.n}
              </div>
              <span className={`text-xs font-medium ${step === s.n ? "text-indigo-600" : "text-gray-400"}`}>{s.label}</span>
              {i < steps.length - 1 && <div className="flex-1 h-px bg-gray-200 dark:bg-gray-600" />}
            </div>
          ))}
        </div>

        {/* Step 1 */}
        {step === 1 && (
          <form onSubmit={submitAccount} className="space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 mb-0.5">Your checking account</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">This is the account your income lands in and bills come out of.</p>
            </div>
            <div>
              <label className="label">Account Name</label>
              <input className="input" value={accountName} onChange={e => setAccountName(e.target.value)} required />
            </div>
            <div>
              <label className="label">Current Balance ($)</label>
              <input type="number" step="0.01" className="input" placeholder="0.00" value={accountBalance} onChange={e => setAccountBalance(e.target.value)} />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button type="submit" disabled={createAccountMut.isPending} className="btn-primary w-full">
              {createAccountMut.isPending ? "Creating…" : "Next →"}
            </button>
          </form>
        )}

        {/* Step 2 */}
        {step === 2 && (
          <form onSubmit={submitIncome} className="space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 mb-0.5">Your main income</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">This drives the forecast. You can add more recurring items later.</p>
            </div>
            <div>
              <label className="label">Name</label>
              <input className="input" value={incomeName} onChange={e => setIncomeName(e.target.value)} />
            </div>
            <div>
              <label className="label">Pay Frequency</label>
              <select className="input" value={incomeFrequency} onChange={e => setIncomeFrequency(e.target.value as any)}>
                <option value="monthly">Monthly (once/month)</option>
                <option value="semimonthly">Semi-monthly (1st &amp; 15th)</option>
                <option value="biweekly">Bi-weekly (every 2 weeks)</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Amount Per Paycheck ($)</label>
                <input type="number" step="0.01" className="input" placeholder="3000.00" value={incomeAmount} onChange={e => setIncomeAmount(e.target.value)} required />
              </div>
              {incomeFrequency === "monthly" && (
                <div>
                  <label className="label">Day of Month</label>
                  <input type="number" min="1" max="31" className="input" value={incomeDay} onChange={e => setIncomeDay(e.target.value)} />
                </div>
              )}
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-3">
              <button type="button" onClick={skipIncome} className="btn-secondary flex-1">Skip</button>
              <button type="submit" disabled={!incomeAmount} className="btn-primary flex-1">
                Next →
              </button>
            </div>
          </form>
        )}

        {/* Step 3 — Credit card (optional) */}
        {step === 3 && (
          <form onSubmit={submitCard} className="space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 mb-0.5">Add a credit card</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">Optional — track balances and project upcoming payments.</p>
            </div>
            <div>
              <label className="label">Card Name</label>
              <input className="input" placeholder="Chase Sapphire" value={cardName} onChange={e => setCardName(e.target.value)} />
            </div>
            <div>
              <label className="label">Credit Limit ($)</label>
              <input type="number" step="0.01" className="input" placeholder="10000" value={cardLimit} onChange={e => setCardLimit(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Statement Day</label>
                <input type="number" min="1" max="31" className="input" value={cardStatementDay} onChange={e => setCardStatementDay(e.target.value)} />
              </div>
              <div>
                <label className="label">Due Day</label>
                <input type="number" min="1" max="31" className="input" value={cardDueDay} onChange={e => setCardDueDay(e.target.value)} />
              </div>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-3">
              <button type="button" onClick={skipCard} className="btn-secondary flex-1">Skip</button>
              <button type="submit" disabled={createCardMut.isPending || !cardName.trim() || !cardLimit} className="btn-primary flex-1">
                {createCardMut.isPending ? "Adding…" : "Next →"}
              </button>
            </div>
          </form>
        )}

        {/* Step 4 — Done */}
        {step === 4 && (
          <div className="space-y-4 text-center">
            <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle size={32} className="text-green-500" />
            </div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">You're all set!</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Head to <strong>Forecast</strong> to see your balance projection, or go to <strong>Settings</strong> to add more accounts and recurring bills.
            </p>
            <button onClick={onComplete} className="btn-primary w-full">Go to Dashboard</button>
          </div>
        )}
      </div>
    </div>
  );
}
