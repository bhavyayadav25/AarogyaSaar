import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { clearJourney } from '../utils/storage';

const AuthContext = createContext(null);
const AUTH_KEY = 'aarogyasaar.auth.v2';

function readAuth() {
  try { return JSON.parse(sessionStorage.getItem(AUTH_KEY) || 'null'); } catch { return null; }
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(readAuth);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (auth?.token) {
        try {
          const status = await api.securityStatus(auth.token);
          if (status.role !== auth.user?.role) throw new Error('Session role mismatch');
          if (auth.user?.role === 'patient') {
            const patient = await api.patient(auth.token, auth.user.id);
            if (patient.id !== auth.user.id) throw new Error('Session patient mismatch');
          }
        } catch (error) {
          if (error?.status === 401) {
            sessionStorage.removeItem(AUTH_KEY);
            if (auth.user?.id) clearJourney(auth.user.id);
            setAuth(null);
          }
        }
      }
      if (alive) setReady(true);
    })();
    return () => { alive = false; };
  }, []);

  async function login(email, password) {
    const result = await api.login({ email, password });
    const next = { token: result.access_token, user: result.user };
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(next));
    setAuth(next);
    return next;
  }

  async function register(payload) {
    const result = await api.register(payload);
    const next = { token: result.access_token, user: result.user };
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(next));
    setAuth(next);
    return next;
  }

  async function logout() {
    const old = auth;
    try { if (old?.token) await api.logout(old.token); } finally {
      sessionStorage.removeItem(AUTH_KEY);
      if (old?.user?.id) clearJourney(old.user.id);
      setAuth(null);
    }
  }

  const value = useMemo(() => ({ ...auth, ready, login, register, logout }), [auth, ready]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
