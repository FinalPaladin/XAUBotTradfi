import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { User } from "@/lib/types";
import {
  getStoredUser,
  hasPermission,
  isAdmin,
  isAuthenticated,
  logout as clearAuth,
  saveAuth,
} from "@/lib/auth";
import { api } from "@/lib/api";
import type { TokenResponse } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  isLoggedIn: boolean;
  login: (response: TokenResponse) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
  can: (permission: string) => boolean;
  isAdminUser: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() =>
    isAuthenticated() ? getStoredUser() : null,
  );

  const login = useCallback((response: TokenResponse) => {
    const saved = saveAuth(response);
    setUser(saved);
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!isAuthenticated()) {
      setUser(null);
      return;
    }
    try {
      const me = await api.getMe();
      sessionStorage.setItem("xaubot_user", JSON.stringify(me));
      setUser(me);
    } catch {
      logout();
    }
  }, [logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoggedIn: Boolean(user && isAuthenticated()),
      login,
      logout,
      refreshUser,
      can: (permission: string) => hasPermission(user, permission),
      isAdminUser: isAdmin(user),
    }),
    [user, login, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
