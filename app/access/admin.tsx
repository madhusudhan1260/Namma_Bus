import React, { useCallback, useEffect, useState } from 'react';
import { Linking, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAccessT } from '../../constants/accessI18n';
import { BottomNav, NavItem, SideNav } from '../../components/access/PortalNav';
import { COLORS, SPACING } from '../../constants/theme';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { accessStyles, Card, Choice, ErrorText, Field, Loading, Row, Stat, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';
import { ConnectionBadge, PassengerCounter } from '../../components/access/PassengerCounter';
import { useLiveTrips } from '../../hooks/useLiveTrips';
import { DashboardError } from '../../components/access/DashboardError';


type SectionKey = 'overview' | 'live' | 'users' | 'students' | 'colleges' | 'conductors' | 'buses' | 'tickets' | 'payments'
  | 'verification' | 'reports' | 'feedback' | 'audit' | 'staff' | 'settings';
type GroupKey = 'dash' | 'live' | 'people' | 'transport' | 'reports' | 'settings';

/** Phones: 6 bottom groups; each group's sections appear as chips. Desktop: every section in the sidebar. */
const GROUPS: Record<GroupKey, SectionKey[]> = {
  dash: ['overview'],
  live: ['live'],
  people: ['users', 'students', 'colleges', 'staff'],
  transport: ['conductors', 'buses', 'tickets', 'payments'],
  reports: ['reports', 'verification', 'feedback', 'audit'],
  settings: ['settings'],
};
const groupOf = (k: SectionKey) => (Object.keys(GROUPS) as GroupKey[]).find(g => GROUPS[g].includes(k)) || 'dash';

function openDocument(relative: string) {
  const url = AccessApi.documentUrl(relative);
  if (Platform.OS === 'web') window.open(url, '_blank', 'noopener');
  else Linking.openURL(url);
}

/** Approve / reject / suspend / reactivate a college. Reject and suspend need a reason (kept in the audit log). */
function CollegeReview({ c, onDone, onError }: { c: any; onDone: () => void; onError: (m: string) => void }) {
  const [detail, setDetail] = useState<any>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const act = async (action: 'approve' | 'reject' | 'suspend' | 'reactivate') => {
    setBusy(true);
    try {
      await AccessApi.adminCollegeAction(c.id, action, reason.trim() || undefined);
      setReason('');
      onDone();
    } catch (e: any) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const needsReason = c.status === 'PENDING' || c.status === 'APPROVED';
  return (
    <Card title={`${c.name} (${c.code})`} right={<StatusBadge status={c.status} />}>
      <Row label="City" value={[c.city, c.state].filter(Boolean).join(', ') || '—'} />
      <Row label="Affiliation" value={c.affiliation || '—'} />
      <Row label="Officer" value={c.officer_name ? `${c.officer_name}${c.officer_designation ? ` (${c.officer_designation})` : ''}` : '—'} />
      <Row label="Official email" value={c.official_email || c.administrators?.[0]?.email || '—'} />
      <Row label="Student requests" value={String(c.verification_requests)} />
      {c.review_reason ? <Row label="Last review note" value={c.review_reason} /> : null}
      {detail ? (
        <>
          <Row label="Address" value={detail.address || '—'} />
          <Row label="Phone" value={detail.phone || '—'} />
          <Row label="Website" value={detail.website || '—'} />
          {detail.document ? (
            <AuthButton variant="link" icon="document-outline" label="Open authorization document" onPress={() => openDocument(detail.document.view_url)} />
          ) : <Text style={accessStyles.muted}>No document on file (created by Super Admin).</Text>}
          {detail.recent_activity.slice(0, 5).map((l: any, i: number) => (
            <Row key={i} label={new Date(l.at).toLocaleString()} value={`${l.action} · ${l.result}`} />
          ))}
        </>
      ) : (
        <AuthButton variant="link" icon="eye-outline" label="View details & document" onPress={() => AccessApi.adminCollege(c.id).then(setDetail).catch(e => onError(e.message))} />
      )}
      {needsReason ? <Field label="Reason (required to reject or suspend)" value={reason} onChangeText={setReason} /> : null}
      <View style={styles.actions}>
        {c.status === 'PENDING' || c.status === 'REJECTED' ? <AuthButton label="APPROVE" icon="checkmark-circle-outline" onPress={() => act('approve')} loading={busy} /> : null}
        {c.status === 'PENDING' ? <AuthButton variant="secondary" label="REJECT" onPress={() => act('reject')} disabled={reason.trim().length < 5} /> : null}
        {c.status === 'APPROVED' ? <AuthButton variant="secondary" label="SUSPEND" onPress={() => act('suspend')} disabled={reason.trim().length < 5} /> : null}
        {c.status === 'SUSPENDED' ? <AuthButton label="REACTIVATE" onPress={() => act('reactivate')} loading={busy} /> : null}
      </View>
    </Card>
  );
}

function StudentRow({ s, onDone, onError }: { s: any; onDone: () => void; onError: (m: string) => void }) {
  const [reason, setReason] = useState('');
  const [open, setOpen] = useState(false);
  const toggle = async (suspend: boolean) => {
    try {
      await AccessApi.adminEligibility(s.id, suspend, reason.trim());
      setOpen(false);
      onDone();
    } catch (e: any) {
      onError(e.message);
    }
  };
  return (
    <View style={styles.log}>
      <Text style={styles.logAction}>{s.name} · {s.email}</Text>
      <Text style={styles.sub}>
        Bus pass: {s.bus_pass_status}{s.college ? ` · ${s.college}` : ''}{s.pass_expiry_date ? ` · valid until ${s.pass_expiry_date}` : ''}
        {s.eligibility_suspended ? ` · ELIGIBILITY SUSPENDED (${s.eligibility_suspended_reason})` : ''}
      </Text>
      {s.eligibility_suspended ? (
        <AuthButton variant="link" label="Reinstate eligibility" onPress={() => toggle(false)} />
      ) : open ? (
        <>
          <Field label="Reason for suspension" value={reason} onChangeText={setReason} />
          <AuthButton variant="secondary" label="SUSPEND ELIGIBILITY" onPress={() => toggle(true)} disabled={reason.trim().length < 5} />
        </>
      ) : (
        <AuthButton variant="link" label="Suspend free-ticket eligibility" onPress={() => setOpen(true)} />
      )}
    </View>
  );
}

function BusEditor({ b, conductors, onDone, onError }: { b: any; conductors: any[]; onDone: () => void; onError: (m: string) => void }) {
  const [reg, setReg] = useState(b.registration_number || '');
  const [route, setRoute] = useState(b.route || '');
  const save = async (extra: Record<string, string> = {}) => {
    try {
      await AccessApi.adminUpdateBus(b.id, { registration_number: reg.trim(), route: route.trim(), ...extra });
      onDone();
    } catch (e: any) {
      onError(e.message);
    }
  };
  const rt = b.realtime || {};
  return (
    <Card title={b.fleet_label} right={<StatusBadge status={b.operational_status} />}>
      <Row label="Conductor" value={b.conductor?.employee_id || 'Not assigned'} />
      {rt.available ? (
        <Row label="Live (BMTC feed)" value={`${rt.current_stop || '—'} → ${rt.next_stop || '—'} · ${rt.age_seconds ?? '?'}s ago`} />
      ) : (
        <Row label="Live" value={`REALTIME DATA UNAVAILABLE${rt.reason ? ` — ${rt.reason}` : ''}`} />
      )}
      <Field label="Registration number (e.g. KA57F4578)" value={reg} onChangeText={setReg} autoCapitalize="characters" />
      <Field label="Route (GTFS number, e.g. 365-P)" value={route} onChangeText={setRoute} autoCapitalize="characters" />
      <Text style={styles.sub}>Assign conductor</Text>
      <Choice options={conductors.filter(c => c.is_active).map(c => ({ value: c.user_id, label: c.employee_id }))} value={b.conductor?.user_id || null}
        onChange={v => save({ conductor_user_id: v })} />
      <Text style={styles.sub}>Operational status</Text>
      <Choice options={[{ value: 'IN_SERVICE', label: 'In service' }, { value: 'OUT_OF_SERVICE', label: 'Out of service' }, { value: 'MAINTENANCE', label: 'Maintenance' }]}
        value={b.operational_status} onChange={v => save({ operational_status: v })} />
      <AuthButton variant="secondary" label="SAVE BUS" onPress={() => save()} />
    </Card>
  );
}

/**
 * Live trips: counts arrive over the WebSocket ("admin" topic); paid/free split and revenue are re-read from
 * the backend whenever a count changes. Nothing is computed on the device.
 */
function LiveTripsPanel({ wide }: { wide: boolean }) {
  const { a } = useAccessT();
  const live = useLiveTrips('admin');
  const [stats, setStats] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const version = live.trips.map(t => `${t.trip_id}:${t.seq}`).join('|');
  useEffect(() => {
    const h = setTimeout(() => AccessApi.adminTripsLive().then(r => (setStats(r), setErr(null))).catch(e => setErr(e.message)), 250);
    return () => clearTimeout(h);
  }, [version]);
  const byId: Record<string, any> = {};
  (stats?.trips || []).forEach((t: any) => (byId[t.trip_id] = t));
  const totalPax = live.trips.reduce((n, t) => n + t.passenger_count, 0);
  return (
    <>
      <Card title="LIVE TRIPS" right={<ConnectionBadge status={live.status} />}>
        <View style={styles.stats}>
          <Stat label="Active trips" value={live.trips.length} />
          <Stat label="Passengers on board" value={totalPax} />
          <Stat label="Revenue (₹, running trips)" value={stats?.totals?.revenue ?? '—'} />
        </View>
        <Text style={accessStyles.muted}>Counted by the server from issued tickets. Paid = verified payments and conductor cash; free = verified eligibility.</Text>
      </Card>
      <ErrorText text={err} />
      {stats?.routes?.length ? (
        <Card title="BY ROUTE">
          {stats.routes.map((r: any) => (
            <Row key={r.route || '—'} label={`${r.route || '—'} · ${r.active_trips} trip${r.active_trips === 1 ? '' : 's'}`}
              value={`${r.passengers}/${r.capacity} · paid ${r.paid_passengers} · free ${r.free_passengers} · ₹${r.revenue}`} />
          ))}
        </Card>
      ) : null}
      {live.loaded && live.trips.length === 0 ? <Notice tone="info" body={a('rtNoActiveTrips')} /> : null}
      {wide && live.trips.length ? (
        <Card title={a('adLive').toUpperCase()}>
          <DataTable
            columns={[a('colRoute'), a('colBus'), a('colConductor'), a('colPassengers'), a('colCapacity'), a('colCurrentStop'), a('colNextStop'), a('colLastUpdate')]}
            rows={live.trips.map(t => {
              const x = byId[t.trip_id] || {};
              return [t.route || '—', t.vehicle_number || t.bus_label || '—', x.conductor_id || '—',
                `${t.occupancy === 'FULL' ? '🔴' : t.occupancy === 'FILLING' ? '🟠' : '🟢'} ${t.passenger_count}`, `${t.max_capacity} (${t.seats_left} free)`,
                x.current_stop || (x.realtime_status ? 'REALTIME DATA UNAVAILABLE' : '—'), x.next_stop || '—', new Date(t.updated_at).toLocaleTimeString()];
            })}
          />
        </Card>
      ) : null}
      {!wide && live.trips.map(t => (
        <View key={t.trip_id}>
          <PassengerCounter trip={t} status={live.status} lastUpdated={live.lastUpdated} size="compact" />
          {byId[t.trip_id] ? (
            <Text style={[accessStyles.muted, { marginTop: -8, marginBottom: 12, marginLeft: 4 }]}>
              {t.route} · paid {byId[t.trip_id].paid_passengers} ({byId[t.trip_id].paid_tickets} tickets) · free {byId[t.trip_id].free_passengers} · ₹{byId[t.trip_id].revenue}
            </Text>
          ) : null}
        </View>
      ))}
    </>
  );
}

/** Big number card for the control centre. */
function MetricCard({ icon, label, value, tone = COLORS.deepNavy, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string;
  value: React.ReactNode; tone?: string; onPress?: () => void }) {
  const body = (
    <>
      <View style={[styles.metricIcon, { backgroundColor: `${tone}18` }]}><Ionicons name={icon} size={20} color={tone} /></View>
      <Text style={[styles.metricValue, { color: tone }]} numberOfLines={1}>{value}</Text>
      <Text style={styles.metricLabel} numberOfLines={2}>{label}</Text>
    </>
  );
  return onPress ? (
    <TouchableOpacity onPress={onPress} accessibilityRole="button" accessibilityLabel={`${label}: ${value}`} style={styles.metric}>{body}</TouchableOpacity>
  ) : (
    <View style={styles.metric}>{body}</View>
  );
}

/**
 * Control centre: today's figures from the backend. Re-read whenever a trip's count changes (admin WebSocket
 * topic), so the cards stay current without reloading the page.
 */
function ControlCentre({ data, onOpen }: { data: any; onOpen: (k: SectionKey) => void }) {
  const { a } = useAccessT();
  const live = useLiveTrips('admin');
  const [stats, setStats] = useState<any>(data.stats);
  const version = live.trips.map(t => `${t.trip_id}:${t.seq}`).join('|');
  useEffect(() => {
    if (!version) return;
    const h = setTimeout(() => AccessApi.adminDashboard().then(d => setStats(d.stats)).catch(() => undefined), 400);
    return () => clearTimeout(h);
  }, [version]);
  const st = stats || {};
  const health = st.system_health || {};
  const healthy = health.database === 'OK';
  return (
    <Card title={a('adControlCentre').toUpperCase()} right={<ConnectionBadge status={live.status} />}>
      <View style={styles.metrics}>
        <MetricCard icon="radio-outline" label={a('adLiveBuses')} value={data.transport?.available ? data.transport.live_buses : '—'} tone="#0F7A3A" />
        <MetricCard icon="pulse-outline" label={a('adActiveTrips')} value={live.loaded ? live.trips.length : st.active_trips ?? '—'} onPress={() => onOpen('live')} />
        <MetricCard icon="people-outline" label={a('adPassengersToday')} value={st.passengers_today ?? '—'} />
        <MetricCard icon="card-outline" label={a('adPaidToday')} value={st.paid_tickets_today ?? '—'} onPress={() => onOpen('payments')} />
        <MetricCard icon="gift-outline" label={a('adFreeToday')} value={st.free_tickets_today ?? '—'} tone="#7C3AED" />
        <MetricCard icon="cash-outline" label={a('adRevenueToday')} value={`₹${(st.revenue_today ?? 0).toLocaleString('en-IN')}`} tone="#0F7A3A" />
        <MetricCard icon="business-outline" label={a('adPendingColleges')} value={st.pending_colleges ?? '—'} tone="#9A5A00" onPress={() => onOpen('colleges')} />
        <MetricCard icon="school-outline" label={a('adPendingPasses')} value={st.pending_student_verifications ?? '—'} tone="#9A5A00" onPress={() => onOpen('students')} />
        <MetricCard icon="alert-circle-outline" label={a('adFailures')} value={st.failed_verification_attempts ?? '—'} tone="#B3141B" onPress={() => onOpen('verification')} />
        <MetricCard icon={healthy ? 'checkmark-circle-outline' : 'warning-outline'} label={a('adSystemHealth')}
          value={healthy ? a('adHealthy') : a('adNeedsAttention')} tone={healthy ? '#0F7A3A' : '#B3141B'} onPress={() => onOpen('settings')} />
      </View>
    </Card>
  );
}

function PaymentsPanel({ data }: { data: any }) {
  const { a } = useAccessT();
  return (
    <>
      <Card title={a('adPaymentsTitle').toUpperCase()}>
        <Row label={a('adPaymentProvider')} value={`${data.provider}${data.is_test ? ' (DEMO PAYMENT — NO REAL MONEY CHARGED)' : ''}`} />
        <Row label={a('status')} value={data.configured ? a('adPaymentConfigured') : a('adPaymentNotConfigured')} />
        {data.provider === 'razorpay' ? <Row label="Webhook" value={data.webhook_configured ? a('adPaymentConfigured') : a('adPaymentNotConfigured')} /> : null}
        <View style={[styles.stats, { marginTop: SPACING.sm }]}>
          {(data.today || []).map((r: any) => <Stat key={r.payment_status} label={`${r.payment_status} · ₹${r.amount}`} value={r.count} />)}
        </View>
      </Card>
      <Card title={a('adRecentPayments').toUpperCase()}>
        <DataTable
          columns={[a('colTime'), a('ticketId'), a('colRoute'), a('colAmount'), a('colStatus')]}
          rows={(data.recent || []).map((p: any) => [new Date(p.created_at).toLocaleString(), p.reference, p.route, `₹${p.fare}`, `${p.payment_status} · ${p.status}`])}
        />
      </Card>
    </>
  );
}

function SettingsPanel({ data }: { data: any }) {
  const { a } = useAccessT();
  const h = data.stats?.system_health || {};
  return (
    <>
      <Card title={a('adSystemHealth').toUpperCase()}>
        <Row label="Database" value={h.database} />
        <Row label="Identity provider" value={`${h.identity_provider}${h.identity_is_development ? ' — DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION' : ''}`} />
        <Row label="Face verification" value={`${h.face_provider}${h.face_is_development ? ' (DEVELOPMENT)' : ''}${h.face_available ? '' : ' · unavailable'}`} />
        <Row label="BMTC realtime" value={data.transport?.available ? `${data.transport.realtime_status || 'OK'} · ${data.transport.live_buses} live buses` : 'REALTIME DATA UNAVAILABLE'} />
        <Row label={a('adPaymentProvider')} value={`${data.payments?.provider}${data.payments?.is_test ? ' (DEMO)' : ''} · ${data.payments?.configured ? a('adPaymentConfigured') : a('adPaymentNotConfigured')}`} />
      </Card>
      <Notice tone="info" body="Secrets (database password, signing keys, payment keys) are set only in the server environment and are never shown here." />
    </>
  );
}

/** Scrollable table on wide screens; stacked rows on phones. Never breaks the layout. */
function DataTable({ columns, rows }: { columns: string[]; rows: React.ReactNode[][] }) {
  const { width } = useWindowDimensions();
  if (!rows.length) return <Text style={accessStyles.muted}>—</Text>;
  if (width < 700) {
    return (
      <>
        {rows.map((r, i) => (
          <View key={i} style={styles.log}>
            {r.map((c, j) => <Row key={j} label={columns[j]} value={c} />)}
          </View>
        ))}
      </>
    );
  }
  return (
    <ScrollView horizontal>
      <View>
        <View style={[styles.tr, styles.th]}>{columns.map(c => <Text key={c} style={[styles.td, styles.thText]}>{c}</Text>)}</View>
        {rows.map((r, i) => (
          <View key={i} style={[styles.tr, i % 2 ? styles.trAlt : null]}>
            {r.map((c, j) => <Text key={j} style={styles.td} numberOfLines={2}>{c}</Text>)}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

export default function AdminPortal() {
  const { ready } = useAccessGuard(['SUPER_ADMIN']);
  const { a } = useAccessT();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<SectionKey>('overview');
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [form, setForm] = useState<Record<string, string>>({});
  const set = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  const load = useCallback(async () => {
    setError(null);
    setData(null);
    try {
      const loaders: Record<string, () => Promise<any>> = {
        overview: AccessApi.adminDashboard,
        live: async () => ({}),
        payments: AccessApi.adminPayments,
        settings: async () => ({ ...(await AccessApi.adminDashboard()), payments: await AccessApi.adminPayments() }),
        users: () => AccessApi.adminUsers(filter || undefined),
        verification: AccessApi.adminVerifications,
        tickets: () => AccessApi.adminTickets(filter || undefined),
        colleges: () => AccessApi.adminColleges(filter || undefined),
        students: () => AccessApi.adminStudents(filter || undefined),
        conductors: async () => ({ ...(await AccessApi.adminConductors()), ...(await AccessApi.adminBuses()) }),
        buses: async () => ({ ...(await AccessApi.adminBuses()), ...(await AccessApi.adminConductors()) }),
        staff: async () => ({ ...(await AccessApi.adminColleges()), ...(await AccessApi.adminBuses()) }),
        reports: () => AccessApi.adminReports(7),
        audit: AccessApi.adminAudit,
        feedback: AccessApi.adminFeedback,
      };
      setData(await loaders[tab]());
    } catch (e: any) {
      setError(e.message);
    }
  }, [tab, filter]);
  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  const [tempPassword, setTempPassword] = useState<{ id: string; pw: string } | null>(null);
  const reportError = (m: string) => setError(m);

  const create = async (kind: 'college' | 'collegeAdmin' | 'conductor' | 'bus') => {
    setError(null);
    setNotice(null);
    try {
      if (kind === 'college') await AccessApi.adminCreateCollege({ code: form.c_code, name: form.c_name, email_domain: form.c_domain });
      if (kind === 'collegeAdmin')
        await AccessApi.adminCreateCollegeAdmin({ name: form.a_name, email: form.a_email, password: form.a_password, college_code: form.a_college });
      if (kind === 'conductor')
        await AccessApi.adminCreateConductor({ name: form.d_name, email: form.d_email || undefined, password: form.d_password, employee_id: form.d_emp,
          bus_id: form.d_bus_id || undefined });
      if (kind === 'bus')
        await AccessApi.adminCreateBus({ fleet_label: form.b_label, route: form.b_route || undefined, registration_number: form.b_reg || undefined });
      setNotice('Created.');
      setForm({});
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const body = () => {
    if (!data && error && tab === 'overview') return <DashboardError detail={error} onRetry={load} />;
    if (!data) return <Loading />;
    switch (tab) {
      case 'live':
        return <LiveTripsPanel wide={width >= 900} />;
      case 'payments':
        return <PaymentsPanel data={data} />;
      case 'settings':
        return <SettingsPanel data={data} />;
      case 'overview':
        return (
          <>
            <ControlCentre data={data} onOpen={k => setTab(k)} />
            <Card title="USERS">
              <View style={styles.stats}>
                <Stat label="Passengers" value={data.users.passengers} />
                <Stat label="Students" value={data.users.students} />
                <Stat label="Conductors" value={data.users.conductors} />
                <Stat label="College admins" value={data.users.college_admins} />
              </View>
            </Card>
            <Card title="VERIFICATION">
              <View style={styles.stats}>
                <Stat label="Pending students" value={data.verification.students_pending} />
                <Stat label="Approved" value={data.verification.students_approved} />
                <Stat label="Rejected" value={data.verification.students_rejected} />
                <Stat label="Identity verified" value={data.verification.identity.VERIFIED || 0} />
              </View>
            </Card>
            <Card title="TRANSPORT">
              {data.transport.available ? (
                <View style={styles.stats}>
                  <Stat label="Live buses" value={data.transport.live_buses} />
                  <Stat label="Routes" value={data.transport.routes} />
                  <Stat label="Stops" value={data.transport.stops} />
                </View>
              ) : (
                <Text style={accessStyles.muted}>{data.transport.message}</Text>
              )}
            </Card>
            <Card title="TICKETS">
              <View style={styles.stats}>
                <Stat label="All" value={data.tickets.total} />
                <Stat label="Paid" value={data.tickets.paid} />
                <Stat label="Eligible / free" value={data.tickets.eligible_free} />
                <Stat label="Invalid scans" value={data.tickets.invalid_scans} />
                <Stat label="Cancelled" value={data.tickets.cancelled} />
              </View>
            </Card>
            {data.stats ? (
              <Card title="ACCESS SYSTEM">
                <View style={styles.stats}>
                  <Stat label="Male passengers" value={data.stats.male_passengers} />
                  <Stat label="Female passengers" value={data.stats.female_passengers} />
                  <Stat label="Verified identities" value={data.stats.verified_identities} />
                  <Stat label="Bus-pass students" value={data.stats.bus_pass_students} />
                  <Stat label="Pending colleges" value={data.stats.pending_colleges} />
                  <Stat label="Approved colleges" value={data.stats.approved_colleges} />
                  <Stat label="Pending student checks" value={data.stats.pending_student_verifications} />
                  <Stat label="Active conductors" value={data.stats.active_conductors} />
                  <Stat label="Active buses" value={data.stats.active_buses} />
                  <Stat label="Free tickets" value={data.stats.tickets_free} />
                  <Stat label="Paid tickets" value={data.stats.tickets_paid} />
                  <Stat label="Failed verifications" value={data.stats.failed_verification_attempts} />
                </View>
                <Text style={[styles.sub, { marginTop: SPACING.sm }]}>
                  System health: database {data.stats.system_health.database} · identity {data.stats.system_health.identity_provider}
                  {data.stats.system_health.identity_is_development ? ' (DEVELOPMENT)' : ''} · face {data.stats.system_health.face_provider}
                  {data.stats.system_health.face_is_development ? ' (DEVELOPMENT)' : ''}
                </Text>
              </Card>
            ) : null}
          </>
        );
      case 'students':
        return (
          <Card title="Students">
            <Field label="Search name or email" value={form.s_q || ''} onChangeText={set('s_q')} />
            <AuthButton variant="secondary" label="SEARCH" onPress={() => setFilter(form.s_q || '')} />
            {data.students.length === 0 ? <Text style={accessStyles.muted}>No students found.</Text> : null}
            {data.students.map((s: any) => <StudentRow key={s.id} s={s} onDone={load} onError={reportError} />)}
          </Card>
        );
      case 'conductors':
        return (
          <>
            {tempPassword ? (
              <Notice tone="warning" title="Temporary password — shown once"
                body={`${tempPassword.pw}\nHand it to the conductor in person. It is not stored in readable form and will not be shown again.`} />
            ) : null}
            {data.conductors.map((c: any) => (
              <Card key={c.user_id} title={`${c.employee_id} · ${c.name}`} right={<StatusBadge status={c.is_active ? 'ACTIVE' : 'DISABLED'} />}>
                <Row label="Bus" value={c.bus ? `${c.bus.fleet_label} · ${c.bus.route || '—'}${c.bus.registration_number ? ` · ${c.bus.registration_number}` : ''}` : 'Not assigned'} />
                <Row label="Active trip" value={c.active_trip_id ? 'Yes' : 'No'} />
                <Row label="Tickets scanned" value={String(c.tickets_scanned)} />
                <Text style={styles.sub}>Assign bus</Text>
                <Choice options={data.buses.map((b: any) => ({ value: b.id, label: `${b.fleet_label} (${b.route || '—'})` }))} value={c.bus?.id || null}
                  onChange={v => AccessApi.adminAssignConductor(c.user_id, v).then(load).catch(e => setError(e.message))} />
                <View style={styles.actions}>
                  <AuthButton variant="secondary" label={c.is_active ? 'DISABLE' : 'ENABLE'}
                    onPress={() => AccessApi.adminSetActive(c.user_id, !c.is_active).then(load).catch(e => setError(e.message))} />
                  <AuthButton variant="secondary" label="RESET PASSWORD"
                    onPress={() => AccessApi.adminResetConductor(c.user_id).then(r => setTempPassword({ id: c.user_id, pw: r.temporary_password })).catch(e => setError(e.message))} />
                </View>
              </Card>
            ))}
          </>
        );
      case 'buses':
        return (
          <>
            <Text style={accessStyles.muted}>
              Live positions come only from the BMTC feed, matched by registration number. A bus without a registration, or one not in the feed, shows REALTIME DATA UNAVAILABLE.
            </Text>
            {data.buses.map((b: any) => <BusEditor key={b.id} b={b} conductors={data.conductors} onDone={load} onError={reportError} />)}
            <Card title="Add bus">
              <Field label="Label (e.g. BUS 4)" value={form.b_label || ''} onChangeText={set('b_label')} autoCapitalize="characters" />
              <Field label="Route (optional)" value={form.b_route || ''} onChangeText={set('b_route')} autoCapitalize="characters" />
              <Field label="Registration number (optional)" value={form.b_reg || ''} onChangeText={set('b_reg')} autoCapitalize="characters" />
              <AuthButton label="ADD BUS" onPress={() => create('bus')} disabled={!(form.b_label || '').trim()} />
            </Card>
          </>
        );
      case 'users':
        return (
          <Card title="Users">
            <Choice options={[{ value: '', label: 'All' }, { value: 'PASSENGER', label: 'Passengers' }, { value: 'STUDENT', label: 'Students' },
              { value: 'CONDUCTOR', label: 'Conductors' }, { value: 'COLLEGE_ADMIN', label: 'Colleges' }]} value={filter} onChange={setFilter} />
            {data.users.map((u: any) => <Row key={u.id} label={`${u.name} · ${u.role}`} value={u.email || u.phone || ''} />)}
          </Card>
        );
      case 'verification':
        return (
          <>
            <Card title="Student verifications">
              {data.student_verifications.map((v: any) => (
                <Row key={v.id} label={`${v.student} · ${v.college}`} value={<StatusBadge status={v.status} />} />
              ))}
            </Card>
            <Card title="Identity verification status">
              {data.identity_verifications.map((v: any, i: number) => (
                <Row key={i} label={`${v.provider}${v.development ? ' (development)' : ''}`} value={<StatusBadge status={v.status} />} />
              ))}
            </Card>
          </>
        );
      case 'tickets':
        return (
          <Card title="Tickets" right={<AuthButton variant="link" icon="download-outline" label="Export CSV" onPress={() => AccessApi.downloadTicketsCsv().catch(e => setError(e.message))} />}>
            <Choice options={[{ value: '', label: 'All' }, { value: 'PAID', label: 'Paid' }, { value: 'ELIGIBLE_FREE', label: 'Eligible/free' },
              { value: 'CANCELLED', label: 'Cancelled' }, { value: 'USED', label: 'Used' }]} value={filter} onChange={setFilter} />
            {data.tickets.map((t: any) => (
              <View key={t.ticket_id} style={styles.log}>
                <Row label={`${t.reference} · ${t.route} · ${t.status}`} value={`₹${t.fare} ${t.eligibility || t.eligibility_type || ''}`} />
                {t.status === 'ISSUED' ? (
                  <AuthButton variant="link" label="Revoke ticket"
                    onPress={() => AccessApi.adminRevokeTicket(t.ticket_id, 'Revoked by Super Admin').then(load).catch(e => setError(e.message))} />
                ) : null}
              </View>
            ))}
            <Text style={[styles.sub, { marginTop: SPACING.md }]}>Invalid scans</Text>
            {data.invalid_scans.map((s: any, i: number) => <Row key={i} label={`${s.result} · ${s.route || '—'}`} value={s.detail} />)}
          </Card>
        );
      case 'colleges':
        return (
          <>
            <Choice options={[{ value: '', label: 'All' }, { value: 'PENDING', label: 'Pending' }, { value: 'APPROVED', label: 'Approved' },
              { value: 'REJECTED', label: 'Rejected' }, { value: 'SUSPENDED', label: 'Suspended' }]} value={filter} onChange={setFilter} />
            {data.colleges.length === 0 ? <Text style={accessStyles.muted}>No colleges in this list.</Text> : null}
            {data.colleges.map((c: any) => <CollegeReview key={c.id} c={c} onDone={load} onError={reportError} />)}
            <Card title="Add college directly (approved)">
              <Field label="College ID (code)" value={form.c_code || ''} onChangeText={set('c_code')} autoCapitalize="characters" />
              <Field label="College name" value={form.c_name || ''} onChangeText={set('c_name')} autoCapitalize="words" />
              <Field label="Official email domain (optional)" value={form.c_domain || ''} onChangeText={set('c_domain')} />
              <AuthButton label="CREATE COLLEGE" onPress={() => create('college')} />
            </Card>
          </>
        );
      case 'staff':
        return (
          <>
            <Card title="Create college administrator">
              <Field label="Name" value={form.a_name || ''} onChangeText={set('a_name')} autoCapitalize="words" />
              <Field label="Official college email" value={form.a_email || ''} onChangeText={set('a_email')} keyboardType="email-address" />
              <Field label="Temporary password" value={form.a_password || ''} onChangeText={set('a_password')} secure />
              <Field label="College ID" value={form.a_college || ''} onChangeText={set('a_college')} autoCapitalize="characters" />
              <AuthButton label="CREATE COLLEGE ADMIN" onPress={() => create('collegeAdmin')} />
            </Card>
            <Card title="Add conductor (Super Admin only)">
              <Field label="Name" value={form.d_name || ''} onChangeText={set('d_name')} autoCapitalize="words" />
              <Field label="Conductor ID (e.g. CONDUCTOR-500D)" value={form.d_emp || ''} onChangeText={set('d_emp')} autoCapitalize="characters" />
              <Field label="Temporary password" value={form.d_password || ''} onChangeText={set('d_password')} secure />
              <Field label="Email (optional)" value={form.d_email || ''} onChangeText={set('d_email')} keyboardType="email-address" />
              <Text style={styles.sub}>Bus</Text>
              <Choice options={(data.buses || []).map((b: any) => ({ value: b.id, label: `${b.fleet_label} (${b.route || '—'})` }))}
                value={form.d_bus_id || null} onChange={set('d_bus_id')} />
              <AuthButton label="ADD CONDUCTOR" onPress={() => create('conductor')} />
            </Card>
          </>
        );
      case 'reports':
        return (
          <>
            <Card title="Daily tickets (7 days)">
              {data.daily_tickets.length === 0 ? <Text style={accessStyles.muted}>No tickets in this period.</Text> : null}
              {data.daily_tickets.map((d: any) => (
                <Row key={d.date} label={d.date} value={`${d.total} total · ${d.paid} paid · ${d.eligible_free} eligible (${d.student_pass} student, ${d.female_verified} verified identity)`} />
              ))}
            </Card>
            <Card title="Verification statistics">
              <Row label="Student submissions" value={String(data.verification_stats.student_submissions)} />
              <Row label="Approved" value={String(data.verification_stats.approved)} />
              <Row label="Rejected" value={String(data.verification_stats.rejected)} />
              <Row label="Pending" value={String(data.verification_stats.pending)} />
            </Card>
          </>
        );
      case 'feedback':
        return (
          <Card title="Problem reports">
            {data.feedback.length === 0 ? <Text style={accessStyles.muted}>No reports yet.</Text> : null}
            {data.feedback.map((f: any) => (
              <View key={f.id} style={styles.log}>
                <Text style={styles.logAction}>{f.category}{f.screen ? ` · ${f.screen}` : ''}</Text>
                <Text style={{ color: COLORS.textPrimary, marginVertical: 2 }}>{f.message}</Text>
                <Text style={styles.sub}>{new Date(f.created_at).toLocaleString()} · {f.signed_in ? 'signed-in user' : 'anonymous'} · {f.status}</Text>
              </View>
            ))}
          </Card>
        );
      case 'audit':
        return (
          <Card title="AUDIT LOGS">
            {data.logs.map((l: any, i: number) => (
              <View key={i} style={styles.log}>
                <Text style={styles.logAction}>{l.action}</Text>
                <Text style={styles.sub}>{new Date(l.at).toLocaleString()} · {l.actor_role || 'anonymous'} · {l.target_type || ''} {l.ip ? `· ${l.ip}` : ''}</Text>
              </View>
            ))}
          </Card>
        );
    }
    return null;
  };

  // Clear the data in the same update as the section change, so a section never renders another section's data
  const select = (k: SectionKey) => { if (k !== tab) setData(null); setTab(k); setFilter(''); setNotice(null); setTempPassword(null); };
  const label: Record<SectionKey, string> = {
    overview: a('adDashboard'), live: a('adLive'), users: a('adPassengers'), students: a('adStudents'), colleges: a('adColleges'),
    conductors: a('adConductors'), buses: a('adBuses'), tickets: a('adTickets'), payments: a('adPayments'), verification: a('adVerifications'),
    reports: a('adReports'), feedback: a('adFeedback'), audit: a('adAudit'), staff: a('adStaff'), settings: a('adSettings'),
  };
  const ICON: Record<SectionKey, keyof typeof Ionicons.glyphMap> = {
    overview: 'grid-outline', live: 'pulse-outline', users: 'people-outline', students: 'school-outline', colleges: 'business-outline',
    conductors: 'id-card-outline', buses: 'bus-outline', tickets: 'ticket-outline', payments: 'card-outline', verification: 'shield-checkmark-outline',
    reports: 'bar-chart-outline', feedback: 'chatbubbles-outline', audit: 'document-text-outline', staff: 'person-add-outline', settings: 'settings-outline',
  };
  const sideItems: NavItem<SectionKey>[] = (Object.keys(label) as SectionKey[]).map(k => ({ key: k, icon: ICON[k], label: label[k] }));
  const groupItems: NavItem<GroupKey>[] = [
    { key: 'dash', icon: 'grid-outline', label: a('adDashboard') },
    { key: 'live', icon: 'pulse-outline', label: a('adLive') },
    { key: 'people', icon: 'people-outline', label: a('adGroupUsers') },
    { key: 'transport', icon: 'bus-outline', label: a('adGroupTransport') },
    { key: 'reports', icon: 'bar-chart-outline', label: a('adReports') },
    { key: 'settings', icon: 'settings-outline', label: a('adSettings') },
  ];
  const group = groupOf(tab);
  const desktop = width >= 1024;

  return (
    <AuthScreen title={label[tab]} subtitle={`Super Admin · ${a('adControlCentre')}`} showBack={false} wide
      sidebar={<SideNav items={sideItems} active={tab} onSelect={select} title="Super Admin" />}
      bottomBar={<BottomNav items={groupItems} active={group} onSelect={g => select(GROUPS[g][0])} />}>
      {!desktop && GROUPS[group].length > 1 ? (
        <Choice options={GROUPS[group].map(k => ({ value: k, label: label[k] }))} value={tab} onChange={v => select(v as SectionKey)} />
      ) : null}
      {notice ? <Notice tone="success" body={notice} /> : null}
      <ErrorText text={error} />
      {body()}
      <AuthButton variant="link" icon="log-out-outline" label="Sign out" onPress={() => AccessApi.logout()} />
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm },
  metric: { flexGrow: 1, flexBasis: 150, minHeight: 112, backgroundColor: '#FFFFFF', borderRadius: 16, borderWidth: 1, borderColor: COLORS.border,
    padding: SPACING.md, gap: 4 },
  metricIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  metricValue: { fontSize: 26, fontWeight: '900' },
  metricLabel: { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary },
  tr: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  trAlt: { backgroundColor: '#F8FAFC' },
  th: { backgroundColor: COLORS.surfaceSubtle },
  td: { width: 150, paddingVertical: 10, paddingHorizontal: 10, fontSize: 13, color: COLORS.textPrimary },
  thText: { fontWeight: '900', color: COLORS.deepNavy },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm },
  sub: { fontSize: 12, color: COLORS.textSecondary },
  log: { paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  logAction: { fontWeight: '800', color: COLORS.textPrimary },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm, marginTop: SPACING.sm },
});
