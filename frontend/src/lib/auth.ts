import type { TokenResponse, User } from "./types";

const TOKEN_KEY = "xaubot_token";
const USER_KEY = "xaubot_user";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function saveAuth(response: TokenResponse): User {
  sessionStorage.setItem(TOKEN_KEY, response.access_token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(response.user));
  return response.user;
}

export function logout(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}

export function hasPermission(user: User | null, permission: string): boolean {
  if (!user) return false;
  if (user.role === "Admin") return true;
  if (user.permissions.includes("admin")) return true;
  return user.permissions.includes(permission);
}

export function isAdmin(user: User | null): boolean {
  if (!user) return false;
  return user.role === "Admin" || user.permissions.includes("admin");
}
