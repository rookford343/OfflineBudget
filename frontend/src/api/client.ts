import axios from "axios";
import { getToken, clearAuth } from "../store/auth";

const DEFAULT_API = `${window.location.protocol}//${window.location.hostname}:8000`;
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? DEFAULT_API,
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
