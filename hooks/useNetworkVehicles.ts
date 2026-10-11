import { useEffect, useRef, useState } from 'react';
import { NetworkApi } from '../services/networkApi';
import { NetworkVehiclesResponse } from '../types/network';

/**
 * Polls BMTC network buses (optionally for one route). `loading` is true only until the first answer.
 * On a failed poll the previous snapshot is kept and `error` is set; an empty feed stays empty.
 */
export function useNetworkVehicles(route?: string, intervalMs = 15000, enabled = true) {
  const [data, setData] = useState<NetworkVehiclesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) {
      setData(null);
      setLoading(false);
      return () => {
        mounted.current = false;
      };
    }
    setLoading(true);
    const load = async () => {
      try {
        const res = await NetworkApi.vehicles(route);
        if (!mounted.current) return;
        setData(res);
        setError(null);
        setUpdatedAt(Date.now());
      } catch (e: any) {
        if (mounted.current) setError(e?.message || 'unavailable');
      } finally {
        if (mounted.current) setLoading(false);
      }
    };
    load();
    const t = setInterval(load, intervalMs);
    return () => {
      mounted.current = false;
      clearInterval(t);
    };
  }, [route, intervalMs, nonce, enabled]);

  /** Manual retry (e.g. a "Try again" button after a failed poll) */
  const refresh = () => setNonce(n => n + 1);

  return { data, vehicles: data?.vehicles ?? [], loading, error, updatedAt, refresh };
}
