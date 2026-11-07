import axios from "axios";
import { getToken, clearAuth } from "../store/auth";
import { isUnreachable, setUnreachable } from "../lib/connection";

const DEFAULT_API = "/api";
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? DEFAULT_API,
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => {
    setUnreachable(false);
    return r;
  },
  (err) => {
    // An HTTP status of any kind (even 401/500) proves the Mac answered.
    if (isUnreachable(err)) {
      if (!axios.isCancel(err)) setUnreachable(true);
    } else if (err.response) {
      setUnreachable(false);
    }
    if (err.response?.status === 401 && !err.config?.url?.startsWith("/auth/")) {
      clearAuth();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);
