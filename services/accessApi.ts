/**
 * Client for the Access module (/api/access): accounts, eligibility, student passes, college,
 * conductor and admin portals. The backend makes every pricing/eligibility decision; this client only
 * sends requests and shows results. No secrets live here.
 */
import { Platform } from 'react-native';
import { API_BASE_URL } from './api';
import { Storage } from './storage';
import { accessTCurrent } from '../constants/accessI18n';

export const ACCESS_BASE = `${API_BASE_URL}/access`;
const SESSION_KEY = 'namma_access_session_v1';
const REQUEST_TIMEOUT_MS = 20000;

export type AccessRole = 'PASSENGER' | 'STUDENT' | 'CONDUCTOR' | 'COLLEGE_ADMIN' | 'SUPER_ADMIN';
export type Portal = 'passenger' | 'conductor' | 'college' | 'admin';

export interface AccessSession {
  access_token: string;
  refresh_token: string;
  role: AccessRole;
  portal: Portal;
  user_id: string;
  next_step?: string;
}

/** Second sign-in step: a 6-digit code was emailed to the account. */
export interface EmailCodeChallenge {
  status: 'EMAIL_CODE_SENT';
  challenge_id: string;
  email_hint: string;
  expires_in: number;
  resend_after: number;
  development_code?: string;
  development_notice?: string;
}

export class AccessError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body?: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

let session: AccessSession | null = null;
let loaded = false;
const listeners = new Set<(s: AccessSession | null) => void>();

export async function loadSession(): Promise<AccessSession | null> {
  if (!loaded) {
    session = await Storage.getItem<AccessSession | null>(SESSION_KEY, null);
    loaded = true;
  }
  return session;
}

async function saveSession(s: AccessSession | null) {
  session = s;
  loaded = true;
  if (s) await Storage.setItem(SESSION_KEY, s);
  else await Storage.removeItem(SESSION_KEY);
  listeners.forEach(l => l(s));
}

export function onSessionChange(cb: (s: AccessSession | null) => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** A clear, translated message for the user. Never a raw status code, SQL error or stack trace. */
function messageFrom(body: any, status: number): string {
  if (status === 0) return accessTCurrent('errNetwork');
  if (status === 408) return accessTCurrent('errTimeout');
  if (status === 429) return accessTCurrent('errTooMany');
  if (status >= 500) return status === 503 ? accessTCurrent('errUnavailable') : accessTCurrent('errServer');
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (d?.message) return d.message;
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, '');
  if (status === 401) return accessTCurrent('errSession');
  return accessTCurrent('errServer');
}

let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (!session?.refresh_token) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${ACCESS_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: session!.refresh_token }),
        });
        if (!res.ok) {
          await saveSession(null);
          return false;
        }
        const body = await res.json();
        await saveSession({ ...session!, ...body });
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function request<T>(path: string, init: RequestInit & { auth?: boolean } = {}, retry = true): Promise<T> {
  await loadSession();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (!(init.body instanceof FormData) && init.body !== undefined) headers['Content-Type'] = 'application/json';
  if (init.auth !== false && session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
  let res: Response;
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = controller && !(init.body instanceof FormData) ? setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS) : null;
  try {
    res = await fetch(`${ACCESS_BASE}${path}`, { ...init, headers, signal: controller?.signal });
  } catch (e: any) {
    if (e?.name === 'AbortError') throw new AccessError(408, messageFrom(null, 408));
    throw new AccessError(0, messageFrom(null, 0));
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (res.status === 401 && retry && init.auth !== false && session?.refresh_token) {
    if (await refreshSession()) return request<T>(path, init, false);
  }
  const text = await res.text();
  const body = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new AccessError(res.status, messageFrom(body, res.status), body);
  return body as T;
}

/** Current access token (for the realtime WebSocket). */
export async function currentAccessToken(): Promise<string | null> {
  await loadSession();
  return session?.access_token ?? null;
}

/** Refresh an expired access token; false when the user must sign in again. */
export const refreshAccessSession = () => refreshSession();

/** One key per purchase attempt: retries of the same tap reuse it, so the backend never creates a second ticket. */
export function newIdempotencyKey(prefix = 'nb'): string {
  const rand = Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 10);
  return `${prefix}-${Date.now().toString(36)}-${rand}`;
}

export interface AccessNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, any>;
  created_at: string | null;
  read: boolean;
}

/** Live passenger count of a running trip, exactly as stored in the backend (never computed on the device). */
export interface LiveTrip {
  trip_id: string;
  trip_code: string | null;
  route: string | null;
  direction: number | null;
  bus_id: string | null;
  bus_label: string | null;
  vehicle_number: string | null;
  status: 'ACTIVE' | 'COMPLETED' | string;
  passenger_count: number;
  max_capacity: number;
  seats_left: number;
  occupancy: 'AVAILABLE' | 'FILLING' | 'FULL';
  started_at: string | null;
  ended_at: string | null;
  updated_at: string;
  seq: number;
}

const post = <T>(path: string, data?: any, auth = true) =>
  request<T>(path, { method: 'POST', body: data instanceof FormData ? data : JSON.stringify(data ?? {}), auth });
const get = <T>(path: string) => request<T>(path);

/** A file picked on web (Blob) or captured on native ({uri}). */
export type PickedFile = { name: string; type: string; blob?: Blob; uri?: string };

export function appendFile(form: FormData, field: string, file: PickedFile) {
  if (Platform.OS === 'web' && file.blob) form.append(field, file.blob, file.name);
  else form.append(field, { uri: file.uri, name: file.name, type: file.type } as any);
}

// ---------------------------------------------------------------------------
// Offline support: issued tickets (with their signed QR) and the profile are cached per user so a
// ticket can be shown to the conductor without internet. Cached data is always marked as offline.
// ---------------------------------------------------------------------------
const cacheKey = (name: string) => `namma_access_cache_v1:${session?.user_id || 'anon'}:${name}`;

async function cached<T>(name: string, fetcher: () => Promise<T>): Promise<T & { offline?: boolean; cached_at?: string }> {
  try {
    const fresh = await fetcher();
    await Storage.setItem(cacheKey(name), { data: fresh, at: new Date().toISOString() });
    return fresh as any;
  } catch (e) {
    if (e instanceof AccessError && e.status === 0) {
      const hit = await Storage.getItem<{ data: T; at: string } | null>(cacheKey(name), null);
      if (hit) return { ...(hit.data as any), offline: true, cached_at: hit.at };
    }
    throw e;
  }
}

export const OFFLINE_LABEL = 'OFFLINE — SHOWING LAST KNOWN DATA';

export interface RecentJourney {
  route: string;
  direction: number;
  from_stop_id: string;
  from_stop: string;
  to_stop_id: string;
  to_stop: string;
}
const RECENT_KEY = () => `namma_access_recent_v1:${session?.user_id || 'anon'}`;

export const AccessApi = {
  session: () => session,
  async recentJourneys(): Promise<RecentJourney[]> {
    await loadSession();
    return Storage.getItem<RecentJourney[]>(RECENT_KEY(), []);
  },
  async rememberJourney(j: RecentJourney) {
    const list = (await AccessApi.recentJourneys()).filter(
      r => !(r.route === j.route && r.from_stop_id === j.from_stop_id && r.to_stop_id === j.to_stop_id)
    );
    await Storage.setItem(RECENT_KEY(), [j, ...list].slice(0, 5));
  },
  feedback: (category: string, message: string, screen?: string) => post<any>('/feedback', { category, message, screen }),
  async deleteAccount(password: string) {
    const r = await post<any>('/me/delete', { password, confirm: 'DELETE' });
    await saveSession(null);
    return r;
  },
  async downloadTicketsCsv(): Promise<void> {
    await loadSession();
    const res = await fetch(`${ACCESS_BASE}/admin/tickets.csv`, { headers: { Authorization: `Bearer ${session?.access_token}` } });
    if (!res.ok) throw new AccessError(res.status, `Export failed (${res.status})`);
    if (Platform.OS === 'web') {
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `namma-bus-tickets-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }
  },
  adminFeedback: () => get<any>('/admin/feedback'),
  loadSession,
  async register(body: {
    name: string; phone: string; email: string; password: string; gender: 'MALE' | 'FEMALE';
    date_of_birth?: string; has_bus_pass?: boolean; has_aadhaar?: boolean;
  }) {
    const s = await post<AccessSession>('/auth/register', body, false);
    await saveSession(s);
    return s;
  },
  /** Password step. Returns a session, or an EMAIL_CODE_SENT challenge when a code was emailed. */
  async login(body: { identifier: string; password: string; portal: Portal; college_code?: string; totp_code?: string }): Promise<AccessSession | EmailCodeChallenge> {
    const r = await post<any>('/auth/login', body, false);
    if (r?.status === 'EMAIL_CODE_SENT') return r as EmailCodeChallenge;
    await saveSession(r);
    return r as AccessSession;
  },
  async loginVerify(challenge_id: string, code: string) {
    const s = await post<AccessSession>('/auth/login/verify', { challenge_id, code }, false);
    await saveSession(s);
    return s;
  },
  /** Conductor portal: Conductor ID + password/PIN. No email code; TOTP if the Super Admin enabled it. */
  async conductorLogin(conductor_id: string, password: string, totp_code?: string) {
    const s = await post<AccessSession>('/conductor/login', { conductor_id, password, totp_code }, false);
    await saveSession(s);
    return s;
  },
  forgotPassword: (identifier: string) => post<{ message: string; development_code?: string; development_notice?: string }>('/auth/password/forgot', { identifier }, false),
  resetPassword: (identifier: string, code: string, new_password: string) =>
    post<{ message: string }>('/auth/password/reset', { identifier, code, new_password }, false),
  sessions: () => get<{ sessions: { id: string; device: string; ip?: string; signed_in_at: string; last_used_at: string; current: boolean }[] }>('/auth/sessions'),
  revokeSession: (id: string) => request<any>(`/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  registerCollege(fields: Record<string, string>, document: PickedFile) {
    const form = new FormData();
    Object.entries(fields).forEach(([k, v]) => v !== '' && v != null && form.append(k, v));
    appendFile(form, 'document', document);
    return post<{ college_id: string; status: string; message: string }>('/colleges/register', form, false);
  },
  // passenger self-service
  profile: () => get<any>('/passenger/profile'),
  updateProfile: (b: { name?: string; date_of_birth?: string }) => request<any>('/passenger/profile', { method: 'PUT', body: JSON.stringify(b) }),
  uploadPhoto(photo: PickedFile) {
    const form = new FormData();
    appendFile(form, 'photo', photo);
    return post<any>('/passenger/profile/photo', form);
  },
  eligibility: () => cached('eligibility', () => get<any>('/passenger/eligibility')),
  loginResend: (challenge_id: string) => post<EmailCodeChallenge>('/auth/login/resend', { challenge_id }, false),
  otpRequest: (identifier: string) => post<{ message: string; development_otp?: string; development_notice?: string }>('/auth/otp/request', { identifier }, false),
  async otpVerify(identifier: string, code: string) {
    const s = await post<AccessSession>('/auth/otp/verify', { identifier, code }, false);
    await saveSession(s);
    return s;
  },
  async logout() {
    try {
      await post('/auth/logout', { refresh_token: session?.refresh_token });
    } catch {
      /* sign out locally regardless */
    }
    await saveSession(null);
  },
  me: () => cached('me', () => get<any>('/me')),
  health: () => get<any>('/health'),
  // identity & face
  aadhaarAnswer: (has_aadhaar: boolean) => post<any>('/identity/aadhaar-answer', { has_aadhaar }),
  identityStart: () => post<any>('/identity/start', { consent: true }),
  identityStatus: () => get<any>('/identity/status'),
  ekycInfo: () =>
    get<{ available: boolean; zip_available: boolean; pdf_available: boolean; max_age_hours: number; download_url: string; message?: string }>(
      '/identity/aadhaar-ekyc/info'
    ),
  /** e-Aadhaar PDF (with its password) or Offline e-KYC ZIP (with its share code). */
  aadhaarUpload(file: PickedFile, secret: string) {
    const form = new FormData();
    form.append('consent', 'true');
    form.append(file.type === 'application/pdf' ? 'pdf_password' : 'share_code', secret);
    appendFile(form, 'ekyc_file', file);
    return post<any>('/identity/aadhaar', form);
  },
  faceVerify(image: PickedFile, mockOutcome?: 'MATCH' | 'NO_MATCH') {
    const form = new FormData();
    form.append('consent', 'true');
    if (mockOutcome) form.append('mock_outcome', mockOutcome);
    appendFile(form, 'image', image);
    return post<any>('/face/verify', form);
  },
  // tickets
  quote: (j: any) => post<any>('/tickets/quote', j),
  createTicket: (j: any) => post<any>('/tickets/create', j),
  payDemo: (id: string, outcome: 'SUCCESS' | 'FAILURE') => post<any>(`/tickets/${id}/pay-demo`, { outcome }),
  paymentOrder: (id: string) => post<any>(`/tickets/${id}/payment/order`, {}),
  paymentCancel: (id: string) => post<any>(`/tickets/${id}/payment/cancel`, {}),
  paymentConfig: () => get<{ provider: string; configured: boolean; is_test: boolean; key_id: string | null; message?: string; label?: string }>('/payments/config'),
  notifications: () => get<{ notifications: AccessNotification[]; unread: number }>('/notifications'),
  notificationsRead: (ids?: string[]) => post<{ marked: number }>('/notifications/read', ids ? { ids } : { all: true }),
  conductorTrips: () => get<{ trips: (LiveTrip & { tickets_issued: number; revenue: number })[] }>('/conductor/trips'),
  adminPayments: () => get<any>('/admin/payments'),
  paymentVerify: (id: string, b: { order_id: string; payment_id: string; signature: string }) => post<any>(`/tickets/${id}/payment/verify`, b),
  tripsActive: (route?: string) => get<{ trips: LiveTrip[] }>(`/trips/active${route ? `?route=${encodeURIComponent(route)}` : ''}`),
  trip: (id: string) => get<{ trip: LiveTrip }>(`/trips/${encodeURIComponent(id)}`),
  tickets: () => cached('tickets', () => get<{ tickets: any[] }>('/tickets')),
  ticket: (id: string) => cached(`ticket:${id}`, () => get<any>(`/tickets/${encodeURIComponent(id)}`)),
  // students
  colleges: () => get<{ colleges: { id: string; code: string; name: string; city?: string }[] }>('/colleges/approved'),
  studentStatus: () => get<any>('/students/pass/status'),
  submitStudent(fields: Record<string, string>, files: { bus_pass: PickedFile; college_id_card?: PickedFile; supporting_document?: PickedFile }) {
    const form = new FormData();
    Object.entries(fields).forEach(([k, v]) => v !== '' && v != null && form.append(k, v));
    appendFile(form, 'bus_pass', files.bus_pass);
    if (files.college_id_card) appendFile(form, 'college_id_card', files.college_id_card);
    if (files.supporting_document) appendFile(form, 'supporting_document', files.supporting_document);
    return post<any>('/students/pass/upload', form);
  },
  // college
  collegeDashboard: () => get<any>('/college/dashboard'),
  collegeStudents: (status?: string, q?: string) => {
    const qs = new URLSearchParams();
    if (status) qs.set('status', status);
    if (q) qs.set('q', q);
    return get<any>(`/college/requests${qs.toString() ? `?${qs}` : ''}`);
  },
  revokePass: (id: string, reason: string) => post<any>(`/college/requests/${id}/revoke`, { reason }),
  collegeStudent: (id: string) => get<any>(`/college/students/${id}`),
  approve: (id: string, pass_expiry_date?: string) => post<any>(`/college/students/${id}/approve`, pass_expiry_date ? { pass_expiry_date } : {}),
  reject: (id: string, reason: string) => post<any>(`/college/students/${id}/reject`, { reason }),
  documentUrl: (relative: string) => `${ACCESS_BASE}/${relative}`,
  // conductor
  conductorMe: () => get<any>('/conductor/me'),
  conductorVerify: (qr_payload: string) => post<any>('/conductor/ticket/verify', { qr_payload, admit: true }),
  conductorBus: () => get<any>('/conductor/bus'),
  tripStart: (direction?: number) => post<any>('/conductor/trip/start', { direction }),
  tripEnd: () => post<any>('/conductor/trip/end', {}),
  conductorTrip: () => get<{ trip: (LiveTrip & { id: string; tickets_issued: number; tickets_scanned: number; valid_tickets: number }) | null }>('/conductor/trip'),
  conductorIssue: (b: { from_stop_id: string; to_stop_id: string; passenger_count: number; fare_category: 'ADULT' | 'CHILD' | 'SENIOR';
    idempotency_key: string; payment_mode?: 'CASH' }) => post<any>('/conductor/tickets/issue', { payment_mode: 'CASH', ...b }),
  adminTripsLive: () => get<any>('/admin/trips/live'),
  // admin
  adminDashboard: () => get<any>('/admin/dashboard'),
  adminUsers: (role?: string) => get<any>(`/admin/users${role ? `?role=${role}` : ''}`),
  adminVerifications: () => get<any>('/admin/verifications'),
  adminTickets: (kind?: string) => get<any>(`/admin/tickets${kind ? `?kind=${kind}` : ''}`),
  adminAudit: () => get<any>('/admin/audit-logs?limit=200'),
  adminReports: (days = 7) => get<any>(`/admin/reports?days=${days}`),
  adminColleges: (status?: string) => get<any>(`/admin/colleges${status ? `?status=${status}` : ''}`),
  adminCollege: (id: string) => get<any>(`/admin/colleges/${id}`),
  adminCollegeAction: (id: string, action: 'approve' | 'reject' | 'suspend' | 'reactivate', reason?: string) =>
    post<any>(`/admin/colleges/${id}/${action}`, reason ? { reason } : {}),
  adminStudents: (q?: string) => get<any>(`/admin/students${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  adminEligibility: (userId: string, suspend: boolean, reason?: string) =>
    post<any>(`/admin/students/${userId}/${suspend ? 'suspend' : 'reinstate'}-eligibility`, suspend ? { reason } : {}),
  adminConductors: () => get<any>('/admin/conductors'),
  adminAssignConductor: (userId: string, bus_id: string) => request<any>(`/admin/conductors/${userId}`, { method: 'PATCH', body: JSON.stringify({ bus_id }) }),
  adminResetConductor: (userId: string) => post<any>(`/admin/conductors/${userId}/reset-credentials`, {}),
  adminSetActive: (userId: string, active: boolean) => post<any>(`/admin/users/${userId}/${active ? 'activate' : 'deactivate'}`, {}),
  adminBuses: () => get<any>('/admin/buses'),
  adminCreateBus: (b: { fleet_label: string; route?: string; registration_number?: string; max_capacity?: number }) => post<any>('/admin/buses', b),
  adminUpdateBus: (id: string, b: { route?: string; registration_number?: string; operational_status?: string; conductor_user_id?: string; max_capacity?: number }) =>
    request<any>(`/admin/buses/${id}`, { method: 'PATCH', body: JSON.stringify(b) }),
  adminRevokeTicket: (id: string, reason: string) => post<any>(`/admin/tickets/${id}/revoke`, { reason }),
  adminCreateCollege: (b: { code: string; name: string; email_domain?: string }) => post<any>('/admin/colleges', b),
  adminCreateCollegeAdmin: (b: any) => post<any>('/admin/college-admins', b),
  adminCreateConductor: (b: any) => post<any>('/admin/conductors', b),
};
