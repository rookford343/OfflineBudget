const KEY = "budget_token";
const USER_KEY = "budget_user";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "viewer";
}

export function isAdmin(): boolean {
  return getUser()?.role === "admin";
}

export function saveAuth(token: string, user: AuthUser): void {
  localStorage.setItem(KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth(): void {
  localStorage.removeItem(KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(KEY);
}

export function getUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
