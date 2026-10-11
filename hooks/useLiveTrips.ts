import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import type { LiveTrip } from '../services/accessApi';
import { realtime, RealtimeStatus } from '../services/realtime';

/**
 * Live trips for one realtime topic (trip:<id> · route:<route> · bus:<id> · admin), always showing the
 * backend's committed values. A snapshot replaces the list; an update replaces a trip only if its `seq` is newer.
 * Pass `null` to subscribe to nothing.
 */
export function useLiveTrips(topic: string | null, opts: { keepEnded?: boolean } = {}) {
  const [trips, setTrips] = useState<LiveTrip[]>([]);
  const [status, setStatus] = useState<RealtimeStatus>(realtime.getStatus());
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const keepEnded = opts.keepEnded ?? topic?.startsWith('trip:') ?? false;
  const keepRef = useRef(keepEnded);
  keepRef.current = keepEnded;

  useEffect(() => realtime.onStatus(setStatus), []);

  useEffect(() => {
    setTrips([]);
    setLoaded(false);
    setLastUpdated(null);
    if (!topic) return;
    const off = realtime.subscribe(topic, (incoming, kind, at) => {
      setLoaded(true);
      setLastUpdated(at);
      setTrips(prev => {
        if (kind === 'snapshot') {
          // keep a newer value we already have (an update can overtake the snapshot read)
          return incoming.map(t => {
            const old = prev.find(p => p.trip_id === t.trip_id);
            return old && old.seq > t.seq ? old : t;
          });
        }
        let next = [...prev];
        for (const t of incoming) {
          const i = next.findIndex(p => p.trip_id === t.trip_id);
          if (i >= 0 && next[i].seq > t.seq) continue;
          if (t.status !== 'ACTIVE' && !keepRef.current) next = next.filter(p => p.trip_id !== t.trip_id);
          else if (i >= 0) next[i] = t;
          else next.push(t);
        }
        return next;
      });
    });
    // Coming back to the foreground: take a fresh authoritative read
    const sub = AppState.addEventListener('change', s => {
      if (s === 'active') realtime.refreshAll();
    });
    return () => {
      off();
      sub.remove();
    };
  }, [topic]);

  const refresh = useCallback(() => realtime.refreshAll(), []);
  return { trips, trip: trips[0] ?? null, status, lastUpdated, loaded, refresh };
}
