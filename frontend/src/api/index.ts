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
};

// ── Accounts ──────────────────────────────────────────────────────────────────
export const accountsApi = {
  list: () => api.get("/accounts").then((r) => r.data),
  create: (data: object) => api.post("/accounts", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/accounts/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/accounts/${id}`),
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
};

// ── Transactions ──────────────────────────────────────────────────────────────
export const transactionsApi = {
  list: (params?: object) => api.get("/transactions", { params }).then((r) => r.data),
  create: (data: object) => api.post("/transactions", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/transactions/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/transactions/${id}`),
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
  logs: (params?: object) => api.get("/admin/logs", { params }).then((r) => r.data),
};

// ── Analytics ─────────────────────────────────────────────────────────────────
export const analyticsApi = {
  availableToSpend: () => api.get("/spending/available-to-spend").then((r) => r.data),
  yearlyTrends: (years?: number) => api.get("/spending/yearly-trends", { params: { years } }).then((r) => r.data),
  rollingMonthly: (months?: number) => api.get("/spending/rolling-monthly", { params: { months } }).then((r) => r.data),
  monthlySummary: (year: number, month: number) =>
    api.get(`/spending/summary/${year}/${month}`).then((r) => r.data),
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
  list: () => api.get("/planned-expenses").then((r) => r.data),
  create: (data: object) => api.post("/planned-expenses", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/planned-expenses/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/planned-expenses/${id}`),
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
