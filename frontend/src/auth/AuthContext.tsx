import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as authApi from "../api/auth";
import { UNAUTHORIZED_EVENT } from "../api/client";
import type { User } from "../types/project";
import { clearSession, readToken, readUser, saveSession, saveUser } from "./session";

type AuthContextValue = {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => (readToken() ? readUser() : null));

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  useEffect(() => {
    if (!readToken()) return;
    let cancelled = false;
    authApi
      .fetchMe()
      .then((me) => {
        if (cancelled) return;
        saveUser(me);
        setUser(me);
      })
      .catch(() => {
        // A 401 is handled by the API interceptor; other failures keep the cached session.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { token, user: next } = await authApi.login({ email, password });
    saveSession(token, next);
    setUser(next);
  }, []);

  const signup = useCallback(async (email: string, password: string, name: string) => {
    const { token, user: next } = await authApi.signup({ email, password, name });
    saveSession(token, next);
    setUser(next);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, login, signup, logout }), [user, login, signup, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react/only-export-components
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>.");
  return value;
}
