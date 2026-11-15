import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, post, setUnauthorizedHandler } from "../lib/api";
import type { User } from "../lib/types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, remember: boolean) => Promise<User>;
  register: (v: { name: string; email: string; password: string; confirm_password: string; accept_terms: boolean }) => Promise<User>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
}
const Ctx = createContext<AuthValue>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try { return await api<User>("/api/auth/me"); }
      catch (e) { if (e instanceof ApiError && e.status === 401) return null; throw e; }
    },
    staleTime: 60_000,
    retry: 1,
  });

  const expire = useCallback(() => {
    qc.clear();
    qc.setQueryData(["me"], null);
    navigate("/login", { state: { expired: true } });
  }, [qc, navigate]);
  useEffect(() => { setUnauthorizedHandler(expire); return () => setUnauthorizedHandler(null); }, [expire]);

  const value: AuthValue = {
    user: me.data ?? null,
    loading: me.isLoading,
    setUser: (u) => qc.setQueryData(["me"], u),
    login: async (email, password, remember) => {
      const u = await post<User>("/api/auth/login", { email, password, remember_me: remember });
      qc.clear(); qc.setQueryData(["me"], u);
      return u;
    },
    register: async (v) => {
      const u = await post<User>("/api/auth/register", v);
      qc.clear(); qc.setQueryData(["me"], u);
      return u;
    },
    logout: async () => {
      try { await post("/api/auth/logout"); } finally { qc.clear(); qc.setQueryData(["me"], null); }
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
