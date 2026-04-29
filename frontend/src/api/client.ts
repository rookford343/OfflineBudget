import axios from "axios";
import { getToken, clearAuth } from "../store/auth";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config?.url?.startsWith("/auth/")) {
      clearAuth();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);
