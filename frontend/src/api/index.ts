export { api } from "./client";

import { api } from "./client";

// ── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }).then((r) => r.data),
  register: (username: string, password: string, display_name: string) =>
    api.post("/auth/register", { username, password, display_name }).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
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
};

// ── Forecast ──────────────────────────────────────────────────────────────────
export const forecastApi = {
  range: (accountId: number, start: string, end: string) =>
    api.get("/forecast", { params: { account_id: accountId, start, end } }).then((r) => r.data),
  quarters: (accountId: number, year: number) =>
    api.get("/forecast/quarters", { params: { account_id: accountId, year } }).then((r) => r.data),
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
