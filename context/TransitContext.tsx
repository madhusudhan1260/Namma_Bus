import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Storage } from '../services/storage';

/**
 * App-wide settings. Transit data itself is never held here: routes, stops and live buses come from the
 * real BMTC network (services/networkApi.ts) and accounts/tickets from services/accessApi.ts.
 * The earlier simulated-corridor state (fake buses, alerts, active journeys, demo controls) was removed.
 */
type Lang = 'EN' | 'KN';

interface TransitContextType {
  preferredLanguage: Lang;
  setPreferredLanguage: (lang: Lang) => void;
}

const LANGUAGE_KEY = 'namma_language_v1';
const TransitContext = createContext<TransitContextType | undefined>(undefined);

export const TransitProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [preferredLanguage, setLang] = useState<Lang>('EN');

  useEffect(() => {
    Storage.getItem<Lang | null>(LANGUAGE_KEY, null).then(stored => {
      if (stored === 'EN' || stored === 'KN') setLang(stored);
    });
  }, []);

  const setPreferredLanguage = useCallback((lang: Lang) => {
    setLang(lang);
    Storage.setItem(LANGUAGE_KEY, lang);
  }, []);

  const value = useMemo(() => ({ preferredLanguage, setPreferredLanguage }), [preferredLanguage, setPreferredLanguage]);
  return <TransitContext.Provider value={value}>{children}</TransitContext.Provider>;
};

export function useTransit(): TransitContextType {
  const ctx = useContext(TransitContext);
  if (!ctx) throw new Error('useTransit must be used within TransitProvider');
  return ctx;
}
