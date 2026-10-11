import { useCallback, useEffect, useState } from 'react';
import { AccessApi, AccessNotification, loadSession, onSessionChange } from '../services/accessApi';
import { realtime } from '../services/realtime';

/**
 * The signed-in user's notifications, from the backend. New ones arrive live over the WebSocket (topic
 * user:<id>); the list is re-read from the server on mount and on refresh. Nothing is generated on the device.
 */
export function useNotifications() {
  const [userId, setUserId] = useState<string | null | undefined>(undefined);
  const [items, setItems] = useState<AccessNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadSession().then(s => setUserId(s?.user_id ?? null));
    return onSessionChange(s => setUserId(s?.user_id ?? null));
  }, []);

  const refresh = useCallback(async () => {
    if (!userId) return;
    try {
      const r = await AccessApi.notifications();
      setItems(r.notifications);
      setUnread(r.unread);
    } catch {
      /* keep what we have */
    } finally {
      setLoaded(true);
    }
  }, [userId]);

  useEffect(() => {
    setItems([]);
    setUnread(0);
    setLoaded(false);
    if (!userId) return;
    refresh();
    return realtime.onNotification(userId, (n: AccessNotification) => {
      setItems(prev => (prev.some(p => p.id === n.id) ? prev : [n, ...prev].slice(0, 50)));
      if (!n.read) setUnread(u => u + 1);
    });
  }, [userId, refresh]);

  const markAllRead = useCallback(async () => {
    await AccessApi.notificationsRead().catch(() => undefined);
    setItems(prev => prev.map(n => ({ ...n, read: true })));
    setUnread(0);
  }, []);

  return { signedIn: !!userId, ready: userId !== undefined, items, unread, loaded, refresh, markAllRead };
}
