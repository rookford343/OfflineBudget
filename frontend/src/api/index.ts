export { api } from "./client";

import { api } from "./client";

// ── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }).then((r) => r.data),
  register: (username: string, password: string, display_name: string) =>
    api.post("/auth/register", { username, password, display_name }).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
  updateMe: (data: object) => api.patch("/auth/me", data).then((r) => r.data),
  changePassword: (data: { current_password: string; new_password: string }) =>
    api.patch("/auth/me/password", data),
  deleteAccount: (data: { password: string }) => api.delete("/auth/me", { data }),
  sendTestEmail: () => api.post("/auth/me/send-test-email"),
  forgotPassword: (username: string) =>
    api.post("/auth/forgot-password", { username }),
  resetPassword: (token: string, new_password: string) =>
    api.post("/auth/reset-password", { token, new_password }),
  resetPasswordWithCode: (username: string, code: string, new_password: string) =>
    api.post("/auth/reset-password-with-code", { username, code, new_password }),
  generateRecoveryCode: (): Promise<{ code: string; created_at: string }> =>
    api.post("/auth/me/recovery-code").then((r) => r.data),
};

// ── Accounts ──────────────────────────────────────────────────────────────────
export const accountsApi = {
  list: () => api.get("/accounts").then((r) => r.data),
  create: (data: object) => api.post("/accounts", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/accounts/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/accounts/${id}`),
};

// ── Bank Sync (SimpleFIN) ────────────────────────────────────────────────────
export const bankSyncApi = {
  connect: (setup_token: string) => api.post("/bank-sync/connect", { setup_token }).then((r) => r.data),
  link: (connectionId: number, data: object) => api.post(`/bank-sync/${connectionId}/link`, data).then((r) => r.data),
  // Re-fetch the accounts discovered on an existing connection. `connect`
  // returns them exactly once and the setup token is spent by then, so this is
  // the only way back to the mapping UI without buying a new token.
  accounts: (connectionId: number) => api.get(`/bank-sync/${connectionId}/accounts`).then((r) => r.data),
  status: () => api.get("/bank-sync/status").then((r) => r.data),
  syncNow: () => api.post("/bank-sync/sync-now").then((r) => r.data),
  schedulerStatus: () => api.get("/bank-sync/scheduler-status").then((r) => r.data),
};

// ── Server settings (admin only) ──────────────────────────────────────────────
export const merchantsApi = {
  listAliases: () => api.get("/merchants/aliases").then((r) => r.data),
  createAlias: (data: object) => api.post("/merchants/aliases", data).then((r) => r.data),
  removeAlias: (id: number) => api.delete(`/merchants/aliases/${id}`),
};

export const appSettingsApi = {
  get: () => api.get("/settings").then((r) => r.data),
  update: (data: object) => api.patch("/settings", data).then((r) => r.data),
  testEmail: () => api.post("/settings/test-email").then((r) => r.data),
  runDailySummary: (toSelfOnly: boolean, includeDigest: boolean) =>
    api.post("/settings/run-daily-summary", null,
      { params: { to_self_only: toSelfOnly, include_digest: includeDigest } }).then((r) => r.data),
  disconnect: (connectionId: number) => api.delete(`/bank-sync/${connectionId}`),
};

// ── Categories ────────────────────────────────────────────────────────────────
export const categoriesApi = {
  list: () => api.get("/categories").then((r) => r.data),
  create: (data: object) => api.post("/categories", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/categories/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/categories/${id}`),
};

// ── Recurring ─────────────────────────────────────────────────────────────────
export const recurringApi = {
  list: (activeOnly = true) => api.get("/recurring", { params: { active_only: activeOnly } }).then((r) => r.data),
  create: (data: object) => api.post("/recurring", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/recurring/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/recurring/${id}`),
  suggestions: (minOccurrences = 2) =>
    api.get("/recurring/suggestions", { params: { min_occurrences: minOccurrences } }).then((r) => r.data),
};

// ── Forecast ──────────────────────────────────────────────────────────────────
export const forecastApi = {
  range: (accountId: number, start: string, end: string) =>
    api.get("/forecast", { params: { account_id: accountId, start, end } }).then((r) => r.data),
  quarters: (accountId: number, year: number) =>
    api.get("/forecast/quarters", { params: { account_id: accountId, year } }).then((r) => r.data),
  quartersWithScenario: (accountId: number, year: number, overrides: object[]) =>
    api.post("/forecast/quarters-scenario", { account_id: accountId, year, overrides }).then((r) => r.data),
  multiYear: (accountId: number, startYear: number, years: number) =>
    api.get("/forecast/multi-year", { params: { account_id: accountId, start_year: startYear, years } }).then((r) => r.data),
  monthlySummary: (accountId: number, year: number, month: number) =>
    api.get("/forecast/monthly-summary", { params: { account_id: accountId, year, month } }).then((r) => r.data),
  risk: (accountId: number, days?: number) =>
    api.get("/forecast/risk", { params: { account_id: accountId, days } }).then((r) => r.data),
};

// ── Transactions ──────────────────────────────────────────────────────────────
export const transactionsApi = {
  list: (params?: object) => api.get("/transactions", { params }).then((r) => r.data),
  create: (data: object) => api.post("/transactions", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/transactions/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/transactions/${id}`),
  // Debug-only -- 404s whenever debug_capture_raw_bank_data was off at sync
  // time, which is the normal case. Callers treat a 404 as "no raw data",
  // not an error.
  raw: (externalId: string) => api.get(`/transactions/raw/${encodeURIComponent(externalId)}`).then((r) => r.data),
};

// ── Budget ────────────────────────────────────────────────────────────────────
export const budgetApi = {
  list: (year: number) => api.get("/budget", { params: { year } }).then((r) => r.data),
  upsert: (data: object) => api.post("/budget", data).then((r) => r.data),
  overview: (year: number, month: number) =>
    api.get("/budget/overview", { params: { year, month } }).then((r) => r.data),
  applyRollover: (year: number, month: number) =>
    api.post(`/budget/rollover/${year}/${month}`).then((r) => r.data),
  setCategoryRollover: (categoryId: number, enabled: boolean) =>
    api.patch(`/budget/categories/${categoryId}/rollover`, { rollover_enabled: enabled }).then((r) => r.data),
};

// ── Credit Cards ──────────────────────────────────────────────────────────────
export const cardsApi = {
  list: () => api.get("/credit-cards").then((r) => r.data),
  create: (data: object) => api.post("/credit-cards", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/credit-cards/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/credit-cards/${id}`),
  pay: (id: number, data: object) => api.post(`/credit-cards/${id}/payment`, data).then((r) => r.data),
  transactions: (id: number, params?: object) =>
    api.get(`/credit-cards/${id}/transactions`, { params }).then((r) => r.data),
  addTransaction: (id: number, data: object) =>
    api.post(`/credit-cards/${id}/transactions`, data).then((r) => r.data),
  updateTransaction: (cardId: number, txnId: number, data: object) =>
    api.patch(`/credit-cards/${cardId}/transactions/${txnId}`, data).then((r) => r.data),
  upcomingDue: () => api.get("/credit-cards/upcoming-due").then((r) => r.data),
};

// ── Spending ──────────────────────────────────────────────────────────────────
export const spendingApi = {
  byCategory: (start: string, end: string, accountId?: number, cardId?: number) =>
    api.get("/spending/by-category", { params: { start, end, account_id: accountId, card_id: cardId } }).then((r) => r.data),
  byCard: (cardId: number, start: string, end: string) =>
    api.get("/spending/by-card", { params: { card_id: cardId, start, end } }).then((r) => r.data),
  monthly: (start: string, end: string, accountId?: number, cardId?: number) =>
    api.get("/spending/monthly", { params: { start, end, account_id: accountId, card_id: cardId } }).then((r) => r.data),
  monthlyByCategory: (start: string, end: string, accountId?: number, cardId?: number) =>
    api.get("/spending/monthly-by-category", { params: { start, end, account_id: accountId, card_id: cardId } }).then((r) => r.data),
  sankey: (year: number, month: number) =>
    api.get(`/spending/sankey/${year}/${month}`).then((r) => r.data),
  byMerchant: (start: string, end: string, accountId?: number, cardId?: number, limit = 50) =>
    api.get("/spending/by-merchant", { params: { start, end, account_id: accountId, card_id: cardId, limit } }).then((r) => r.data),
  lineItems: (start: string, end: string, accountId?: number, cardId?: number, limit = 25) =>
    api.get("/spending/transactions", { params: { start, end, account_id: accountId, card_id: cardId, limit } }).then((r) => r.data),
  taxEstimate: (year: number) => api.get("/spending/tax-estimate", { params: { year } }).then((r) => r.data),
  taxSummaryUrl: (year: number) => `/spending/tax-summary?year=${year}&format=csv`,
};

// ── Reconciliation ────────────────────────────────────────────────────────────
export const reconciliationApi = {
  get: (accountId: number, year: number, month: number) =>
    api.get("/reconciliation", { params: { account_id: accountId, year, month } }).then((r) => r.data),
};

// ── Import ────────────────────────────────────────────────────────────────────
export const importApi = {
  preview: (formData: FormData) =>
    api.post("/import/preview", formData, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data),
  confirm: (data: object) => api.post("/import/confirm", data).then((r) => r.data),
};

// ── Admin ─────────────────────────────────────────────────────────────────────
export const adminApi = {
  listUsers: () => api.get("/admin/users").then((r) => r.data),
  createUser: (data: object) => api.post("/admin/users", data).then((r) => r.data),
  updateUser: (id: number, data: object) => api.patch(`/admin/users/${id}`, data).then((r) => r.data),
  removeUser: (id: number) => api.delete(`/admin/users/${id}`),
  resetPassword: (id: number, new_password: string) =>
    api.post(`/admin/users/${id}/reset-password`, { new_password }),
  logs: (params?: object) => api.get("/admin/logs", { params }).then((r) => r.data),
};

// ── Analytics ─────────────────────────────────────────────────────────────────
export const analyticsApi = {
  availableToSpend: () => api.get("/spending/available-to-spend").then((r) => r.data),
  yearlyTrends: (years?: number) => api.get("/spending/yearly-trends", { params: { years } }).then((r) => r.data),
  rollingMonthly: (months?: number) => api.get("/spending/rolling-monthly", { params: { months } }).then((r) => r.data),
  monthlySummary: (year: number, month: number) =>
    api.get(`/spending/summary/${year}/${month}`).then((r) => r.data),
  weeklyDigest: (accountId: number) =>
    api.get("/spending/weekly-digest", { params: { account_id: accountId } }).then((r) => r.data),
  budgetSnapshot: (accountId: number) =>
    api.get("/spending/budget-snapshot", { params: { account_id: accountId } }).then((r) => r.data),
};

// ── Savings Goals ─────────────────────────────────────────────────────────────
export const goalsApi = {
  list: () => api.get("/goals").then((r) => r.data),
  create: (data: object) => api.post("/goals", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/goals/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/goals/${id}`),
};

// ── Net Worth ─────────────────────────────────────────────────────────────────
export const netWorthApi = {
  totals: () => api.get("/net-worth").then((r) => r.data),
  history: () => api.get("/net-worth/history").then((r) => r.data),
  snapshot: () => api.post("/net-worth/snapshot").then((r) => r.data),
  listAssets: () => api.get("/net-worth/assets").then((r) => r.data),
  listLiabilities: () => api.get("/net-worth/liabilities").then((r) => r.data),
  createAsset: (data: object) => api.post("/net-worth/assets", data).then((r) => r.data),
  updateAsset: (id: number, data: object) => api.patch(`/net-worth/assets/${id}`, data).then((r) => r.data),
  removeAsset: (id: number) => api.delete(`/net-worth/assets/${id}`),
  createLiability: (data: object) => api.post("/net-worth/liabilities", data).then((r) => r.data),
  updateLiability: (id: number, data: object) => api.patch(`/net-worth/liabilities/${id}`, data).then((r) => r.data),
  removeLiability: (id: number) => api.delete(`/net-worth/liabilities/${id}`),
};

// ── Planned Expenses ─────────────────────────────────────────────────────────
export const plannedExpensesApi = {
  list: (includeSettled = false) =>
    api.get("/planned-expenses", { params: { include_settled: includeSettled } }).then((r) => r.data),
  create: (data: object) => api.post("/planned-expenses", data).then((r) => r.data),
  settle: (id: number, actual_amount: number | null) =>
    api.post(`/planned-expenses/${id}/settle`, { actual_amount }).then((r) => r.data),
  unsettle: (id: number) => api.post(`/planned-expenses/${id}/unsettle`).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/planned-expenses/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/planned-expenses/${id}`),
};

// ── Planned Transfers ────────────────────────────────────────────────────────
export const plannedTransfersApi = {
  list: () => api.get("/planned-transfers").then((r) => r.data),
  create: (data: object) => api.post("/planned-transfers", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/planned-transfers/${id}`, data).then((r) => r.data),
  markScheduled: (id: number) => api.post(`/planned-transfers/${id}/mark-scheduled`).then((r) => r.data),
  remove: (id: number) => api.delete(`/planned-transfers/${id}`),
};

// ── Scenarios ─────────────────────────────────────────────────────────────────
export const scenariosApi = {
  list: () => api.get("/scenarios").then((r) => r.data),
  create: (data: object) => api.post("/scenarios", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/scenarios/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/scenarios/${id}`),
  createOverride: (scenarioId: number, data: object) =>
    api.post(`/scenarios/${scenarioId}/overrides`, data).then((r) => r.data),
  removeOverride: (scenarioId: number, overrideId: number) =>
    api.delete(`/scenarios/${scenarioId}/overrides/${overrideId}`),
};

// ── Day Checkpoints ───────────────────────────────────────────────────────────
export const dayCheckpointsApi = {
  list: (accountId: number) =>
    api.get("/forecast/day-checkpoints", { params: { account_id: accountId } }).then((r) => r.data),
  upsert: (date: string, accountId: number, actualBalance: number, note?: string) =>
    api.put(`/forecast/day-checkpoints/${date}`, { account_id: accountId, actual_balance: actualBalance, note: note ?? null }).then((r) => r.data),
  remove: (date: string, accountId: number) =>
    api.delete(`/forecast/day-checkpoints/${date}`, { params: { account_id: accountId } }),
};

// ── Transaction Rules ─────────────────────────────────────────────────────────
export const rulesApi = {
  list: () => api.get("/rules").then((r) => r.data),
  create: (data: object) => api.post("/rules", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/rules/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/rules/${id}`),
  test: (data: { pattern: string; pattern_type: string; description: string }) =>
    api.post("/rules/test", data).then((r) => r.data),
};

// ── Data Management ───────────────────────────────────────────────────────────
export const dataApi = {
  clearTransactions: () => api.delete("/data/transactions"),
  clearCCTransactions: () => api.delete("/data/cc-transactions"),
};

// ── Export ────────────────────────────────────────────────────────────────────
export const exportsApi = {
  downloadTransactions: (params: object) =>
    api.get("/export/transactions", { params, responseType: "blob" }).then((r) => r.data),
  downloadBudgetReport: (year: number, month: number, format = "csv") =>
    api.get("/export/budget-report", { params: { year, month, format }, responseType: "blob" }).then((r) => r.data),
};

// ── Verification Flags ──────────────────────────────────────────────────────
export const verificationFlagsApi = {
  list: (params?: { feature?: string; status?: string }) =>
    api.get("/verification-flags", { params }).then((r) => r.data),
  create: (data: {
    feature: string;
    reference_type?: string;
    reference_id?: number;
    observed: object;
    expected_value?: number;
    note?: string;
  }) => api.post("/verification-flags", data).then((r) => r.data),
  resolve: (id: number, newStatus: "open" | "resolved") =>
    api.patch(`/verification-flags/${id}`, { status: newStatus }).then((r) => r.data),
};
