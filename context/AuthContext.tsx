import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { AuthApi, AuthApiError } from '../services/authApi';
import { Storage } from '../services/storage';
import { AuthSession, AuthUserDto } from '../types/auth';

/**
 * Phase 41: Commuter auth session.
 *
 * Kept separate from TransitContext so signing in or out never touches saved journeys, favourites,
 * tickets, the active journey or preferences. Only the opaque session token and the safe account
 * view (masked mobile, statuses) are held on the device.
 */

const AUTH_STORAGE_KEY = 'nammablr_auth_session';
const GUEST_STORAGE_KEY = 'nammablr_auth_guest';

interface AuthContextType {
  authReady: boolean;
  session: AuthSession | null;
  guestMode: boolean;
  setSession: (session: AuthSession) => Promise<void>;
  refreshUser: () => Promise<AuthUserDto | null>;
  logout: () => Promise<void>;
  continueAsGuest: () => Promise<void>;
  clearLocalAuth: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [authReady, setAuthReady] = useState(false);
  const [session, setSessionState] = useState<AuthSession | null>(null);
  const [guestMode, setGuestMode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await Storage.getItem<AuthSession | null>(AUTH_STORAGE_KEY, null);
      const guest = await Storage.getItem<boolean>(GUEST_STORAGE_KEY, false);
      if (stored?.token) {
        try {
          const user = await AuthApi.me(stored.token);
          if (!cancelled) setSessionState({ token: stored.token, user });
        } catch (err) {
          if (err instanceof AuthApiError && err.status === 401) {
            await Storage.removeItem(AUTH_STORAGE_KEY);
          } else if (!cancelled) {
            // Offline: keep the last known safe account view rather than signing the commuter out.
            setSessionState(stored);
          }
        }
      }
      if (!cancelled) {
        setGuestMode(guest);
        setAuthReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setSession = useCallback(async (next: AuthSession) => {
    setSessionState(next);
    setGuestMode(false);
    await Storage.setItem(AUTH_STORAGE_KEY, next);
    await Storage.removeItem(GUEST_STORAGE_KEY);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!session) return null;
    try {
      const user = await AuthApi.me(session.token);
      const next = { token: session.token, user };
      setSessionState(next);
      await Storage.setItem(AUTH_STORAGE_KEY, next);
      return user;
    } catch (err) {
      if (err instanceof AuthApiError && err.status === 401) {
        setSessionState(null);
        await Storage.removeItem(AUTH_STORAGE_KEY);
      }
      return null;
    }
  }, [session]);

  const logout = useCallback(async () => {
    const token = session?.token;
    setSessionState(null);
    setGuestMode(false);
    await Storage.removeItem(AUTH_STORAGE_KEY);
    await Storage.removeItem(GUEST_STORAGE_KEY);
    if (token) {
      try {
        await AuthApi.logout(token);
      } catch {
        // Local sign-out already done; the server session expires on its own.
      }
    }
  }, [session]);

  const continueAsGuest = useCallback(async () => {
    setGuestMode(true);
    await Storage.setItem(GUEST_STORAGE_KEY, true);
  }, []);

  /** Used by demo reset: the backend has already dropped all sessions. */
  const clearLocalAuth = useCallback(() => {
    setSessionState(null);
    setGuestMode(false);
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({ authReady, session, guestMode, setSession, refreshUser, logout, continueAsGuest, clearLocalAuth }),
    [authReady, session, guestMode, setSession, refreshUser, logout, continueAsGuest, clearLocalAuth]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
