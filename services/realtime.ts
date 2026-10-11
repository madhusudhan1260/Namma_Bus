/**
 * Realtime trip updates from the backend WebSocket (/api/access/ws).
 *
 * The backend (PostgreSQL) owns every passenger count. This client never changes a count itself: it only shows
 * the latest committed value it received — a SNAPSHOT when it (re)subscribes, then PASSENGER_COUNT_UPDATED /
 * TRIP_STATE messages. Each message carries `seq`, so an older message arriving late can't overwrite a newer one.
 *
 * Connection loss: reconnects with exponential backoff (1 s → 30 s, with jitter) and, after reconnecting, takes
 * a fresh snapshot. While disconnected, and only then, each topic is refreshed over REST every 12 s.
 */
import { ACCESS_BASE, AccessApi, LiveTrip, currentAccessToken, refreshAccessSession } from './accessApi';

export type RealtimeStatus = 'connecting' | 'live' | 'reconnecting' | 'offline';
export type TripsListener = (trips: LiveTrip[], kind: 'snapshot' | 'update', at: number) => void;

const POLL_MS = 12000;
const PING_MS = 25000;
const MAX_BACKOFF_MS = 30000;

export const normRoute = (r?: string | null) => (r || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

export function topicsOf(t: LiveTrip): string[] {
  const out = [`trip:${t.trip_id}`, 'admin'];
  if (t.route) out.push(`route:${normRoute(t.route)}`);
  if (t.bus_id) out.push(`bus:${t.bus_id}`);
  return out;
}

/** REST fallback for a topic (used only while the socket is down). */
async function fetchTopic(topic: string): Promise<LiveTrip[]> {
  const [kind, value] = [topic.split(':')[0], topic.slice(topic.indexOf(':') + 1)];
  if (kind === 'user') return [];
  if (kind === 'trip') return [(await AccessApi.trip(value)).trip];
  if (kind === 'route') return (await AccessApi.tripsActive(value)).trips;
  if (kind === 'bus') {
    const t = (await AccessApi.conductorTrip()).trip;
    return t ? [t] : [];
  }
  return ((await AccessApi.adminTripsLive()).trips || []) as LiveTrip[];
}

class RealtimeClient {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<TripsListener>>();
  private statusListeners = new Set<(s: RealtimeStatus) => void>();
  private status: RealtimeStatus = 'offline';
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private authRetried = false;
  private notificationListeners = new Set<(n: any) => void>();

  /** Live notifications for the signed-in user (topic user:<id>). */
  onNotification(userId: string, cb: (n: any) => void): () => void {
    this.notificationListeners.add(cb);
    const off = this.subscribe(`user:${userId}`, () => undefined);
    return () => {
      this.notificationListeners.delete(cb);
      off();
    };
  }

  getStatus() {
    return this.status;
  }

  onStatus(cb: (s: RealtimeStatus) => void): () => void {
    this.statusListeners.add(cb);
    cb(this.status);
    return () => {
      this.statusListeners.delete(cb);
    };
  }

  subscribe(topic: string, cb: TripsListener): () => void {
    let set = this.listeners.get(topic);
    const isNew = !set;
    if (!set) this.listeners.set(topic, (set = new Set()));
    set.add(cb);
    if (this.ws && this.ws.readyState === 1 && isNew) this.send({ action: 'subscribe', topics: [topic] });
    else if (this.ws && this.ws.readyState === 1) this.pollTopic(topic, cb); // already subscribed: give this listener current state
    if (!this.ws) this.connect();
    if (this.status !== 'live') this.pollTopic(topic, cb);
    return () => {
      const s = this.listeners.get(topic);
      if (!s) return;
      s.delete(cb);
      if (s.size === 0) {
        this.listeners.delete(topic);
        this.send({ action: 'unsubscribe', topics: [topic] });
      }
      if (this.listeners.size === 0) this.shutdown();
    };
  }

  /** Re-read every subscribed topic now (e.g. after an action, or when the app comes back to the foreground). */
  refreshAll() {
    if (this.ws && this.ws.readyState === 1) this.send({ action: 'subscribe', topics: [...this.listeners.keys()] });
    else this.listeners.forEach((set, topic) => set.forEach(cb => this.pollTopic(topic, cb)));
  }

  private setStatus(s: RealtimeStatus) {
    if (this.status === s) return;
    this.status = s;
    this.statusListeners.forEach(cb => cb(s));
    if (s === 'live') this.stopPolling();
    else if (this.listeners.size) this.startPolling();
  }

  private send(msg: object) {
    try {
      if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg));
    } catch {
      /* the close handler reconnects */
    }
  }

  private async connect() {
    if (this.ws || this.listeners.size === 0) return;
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting');
    const token = await currentAccessToken();
    if (!token) {
      this.setStatus('offline');
      return;
    }
    // The token goes in the first message, never in the URL (URLs end up in server and proxy logs)
    const url = `${ACCESS_BASE.replace(/^http/, 'ws')}/ws`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      try {
        ws.send(JSON.stringify({ action: 'auth', token }));
      } catch {
        /* onclose reconnects */
      }
    };
    ws.onmessage = ev => this.handle(ev.data);
    ws.onerror = () => {
      /* onclose follows */
    };
    ws.onclose = () => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = null;
      if (this.ws === ws) this.ws = null;
      if (this.listeners.size) this.scheduleReconnect();
      else this.setStatus('offline');
    };
  }

  private async handle(raw: any) {
    let msg: any;
    try {
      msg = JSON.parse(String(raw));
    } catch {
      return;
    }
    const now = Date.now();
    if (msg.type === 'AUTH_OK') {
      this.attempt = 0;
      this.setStatus('live');
      // (Re)subscribe → the server answers each topic with a fresh snapshot from the database
      this.send({ action: 'subscribe', topics: [...this.listeners.keys()] });
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.send({ action: 'ping' }), PING_MS);
      return;
    }
    if (msg.type === 'NOTIFICATION' && msg.notification) {
      this.notificationListeners.forEach(cb => cb(msg.notification));
      return;
    }
    if (msg.type === 'SNAPSHOT') {
      this.authRetried = false;
      this.listeners.get(msg.topic)?.forEach(cb => cb(msg.trips || [], 'snapshot', now));
    } else if ((msg.type === 'PASSENGER_COUNT_UPDATED' || msg.type === 'TRIP_STATE') && msg.trip) {
      for (const topic of topicsOf(msg.trip)) this.listeners.get(topic)?.forEach(cb => cb([msg.trip], 'update', now));
    } else if (msg.type === 'ERROR' && msg.code === 'UNAUTHORIZED') {
      // Expired access token: refresh once, then reconnect with the new one
      if (!this.authRetried && (await refreshAccessSession())) {
        this.authRetried = true;
        this.attempt = 0;
      } else {
        this.setStatus('offline');
        this.listeners.clear();
      }
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.setStatus('reconnecting');
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt) * (0.8 + Math.random() * 0.4);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private pollTopic(topic: string, cb?: TripsListener) {
    fetchTopic(topic)
      .then(trips => {
        const targets = cb ? [cb] : [...(this.listeners.get(topic) || [])];
        targets.forEach(l => l(trips, 'snapshot', Date.now()));
      })
      .catch(() => {
        /* keep showing the last confirmed value, marked as not live */
      });
  }

  private startPolling() {
    if (this.pollTimer) return;
    this.pollTimer = setInterval(() => this.listeners.forEach((_, topic) => this.pollTopic(topic)), POLL_MS);
  }

  private stopPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  private shutdown() {
    this.stopPolling();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const ws = this.ws;
    this.ws = null;
    this.attempt = 0;
    try {
      ws?.close();
    } catch {
      /* already closed */
    }
    this.setStatus('offline');
  }
}

export const realtime = new RealtimeClient();
