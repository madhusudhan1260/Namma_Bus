import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { haptic } from '../../components/ui/haptics';
import { BottomNav, SideNav } from '../../components/access/PortalNav';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen } from '../../components/auth/AuthUi';
import { accessStyles, Card, Choice, ErrorText, Loading, Row, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { TicketQrScanner } from '../../components/conductor/TicketQrScanner';
import { DashboardError } from '../../components/access/DashboardError';
import { PassengerCounter } from '../../components/access/PassengerCounter';
import { useLiveTrips } from '../../hooks/useLiveTrips';
import { AccessApi, newIdempotencyKey } from '../../services/accessApi';
import { NetworkApi } from '../../services/networkApi';
import { NetworkStop } from '../../types/network';

const RESULT_STYLE: Record<string, { bg: string; fg: string }> = {
  VALID: { bg: '#E3F6EA', fg: '#0F5F30' },
  EXPIRED: { bg: '#EEF0F4', fg: '#44506A' },
  ALREADY_USED: { bg: '#FFF4DB', fg: '#7A4B00' },
  INVALID: { bg: '#FDE8E8', fg: '#8E1C1C' },
  REVOKED: { bg: '#FDE8E8', fg: '#8E1C1C' },
  WRONG_ROUTE: { bg: '#FFF4DB', fg: '#7A4B00' },
  WRONG_BUS: { bg: '#FFF4DB', fg: '#7A4B00' },
  WRONG_TRIP: { bg: '#FFF4DB', fg: '#7A4B00' },
};
const REALTIME_REFRESH_MS = 20000;
type Section = 'dashboard' | 'tickets' | 'scanner' | 'trip' | 'profile';

/** Large, high-contrast, one-hand button for the conductor. */
function BigButton({ icon, label, color, onPress, loading, disabled }: { icon: keyof typeof Ionicons.glyphMap; label: string; color: string;
  onPress: () => void; loading?: boolean; disabled?: boolean }) {
  return (
    <TouchableOpacity onPress={onPress} disabled={disabled || loading} accessibilityRole="button" accessibilityLabel={label}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
      style={[styles.big, { backgroundColor: color }, (disabled || loading) && { opacity: 0.45 }]}>
      {loading ? <ActivityIndicator color="#FFFFFF" /> : <Ionicons name={icon} size={26} color="#FFFFFF" />}
      <Text style={styles.bigText}>{label}</Text>
    </TouchableOpacity>
  );
}

/** Conductor portal: assignment, QR scanning and validation. Conductors cannot change eligibility. */
export default function ConductorPortal() {
  const { ready } = useAccessGuard(['CONDUCTOR']);
  const { a } = useAccessT();
  const [me, setMe] = useState<any>(null);
  const [scanning, setScanning] = useState(false);
  const [manual, setManual] = useState('');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<any>(null);
  const [direction, setDirection] = useState<string>('0');
  const [tripBusy, setTripBusy] = useState(false);
  // Authoritative live count for this conductor's bus (WebSocket; REST only while disconnected)
  const counter = useLiveTrips(me?.bus?.id ? `bus:${me.bus.id}` : null);
  const liveTrip = counter.trips.find(t => t.status === 'ACTIVE') || null;

  const load = useCallback(() => {
    AccessApi.conductorMe().then(setMe).catch(e => setError(e.message));
  }, []);
  const loadLive = useCallback(() => {
    AccessApi.conductorBus().then(setLive).catch(() => setLive(null));
  }, []);
  useEffect(() => {
    if (!ready) return;
    load();
    loadLive();
    const t = setInterval(loadLive, REALTIME_REFRESH_MS);
    return () => clearInterval(t);
  }, [ready, load, loadLive]);

  const trip = async (start: boolean) => {
    setTripBusy(true);
    setError(null);
    try {
      if (start) await AccessApi.tripStart(Number(direction));
      else await AccessApi.tripEnd();
      haptic.success();
      load();
      counter.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setTripBusy(false);
    }
  };

  const verify = async (qr: string) => {
    setScanning(false);
    setBusy(true);
    setError(null);
    try {
      const r = await AccessApi.conductorVerify(qr.trim());
      setResult(r);
      if (r.result === 'VALID') haptic.success();
      else haptic.error();
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const [section, setSection] = useState<Section>('dashboard');
  const [history, setHistory] = useState<any[] | null>(null);
  useEffect(() => {
    if (section === 'trip' && ready) AccessApi.conductorTrips().then(r => setHistory(r.trips)).catch(() => setHistory([]));
  }, [section, ready, liveTrip?.status]);

  if (!me) {
    return (
      <AuthScreen title={a('conductorDashboard')} showBack={false}>
        {error ? <DashboardError detail={error} onRetry={() => { setError(null); load(); loadLive(); }} /> : <Loading />}
      </AuthScreen>
    );
  }

  const rs = result ? RESULT_STYLE[result.result] || RESULT_STYLE.INVALID : null;
  const stops = live?.realtime?.available ? { current: live.realtime.current_stop, next: live.realtime.next_stop } : null;
  const NAV: { key: Section; icon: keyof typeof Ionicons.glyphMap; label: string }[] = [
    { key: 'dashboard', icon: 'speedometer-outline', label: a('cdTabDashboard') },
    { key: 'tickets', icon: 'ticket-outline', label: a('cdTabTickets') },
    { key: 'scanner', icon: 'qr-code-outline', label: a('cdTabScanner') },
    { key: 'trip', icon: 'bus-outline', label: a('cdTabTrip') },
    { key: 'profile', icon: 'person-outline', label: a('cdTabProfile') },
  ];
  const go = (k: Section) => {
    haptic.tap();
    setSection(k);
    if (k === 'scanner') setResult(null);
  };

  const counterCard = liveTrip ? (
    <PassengerCounter trip={liveTrip} status={counter.status} lastUpdated={counter.lastUpdated} size="large" stops={stops} />
  ) : (
    <Card>
      <Text style={styles.noTrip}>{a('rtNoTrip')}</Text>
      <Text style={accessStyles.muted}>{a('rtStartTripHint')}</Text>
    </Card>
  );

  const startTripControls = (
    <>
      <Text style={accessStyles.muted}>{a('direction')}</Text>
      <Choice options={[{ value: '0', label: a('directionUp') }, { value: '1', label: a('directionDown') }]} value={direction} onChange={setDirection} />
      <BigButton icon="play-circle" label={a('startTrip')} color="#0F7A3A" onPress={() => trip(true)} loading={tripBusy} disabled={!me.bus} />
    </>
  );

  const body = () => {
    switch (section) {
      case 'dashboard':
        return (
          <>
            <View style={styles.busHead}>
              <Text style={styles.busRoute}>{me.assigned_route || '—'}</Text>
              <Text style={styles.busMeta}>{me.employee_id}{me.bus ? ` · ${me.bus.fleet_label}` : ''}</Text>
            </View>
            {counterCard}
            {!liveTrip ? startTripControls : (
              <View style={styles.bigGrid}>
                <BigButton icon="ticket" label={a('rtIssueTicket')} color={COLORS.deepNavy} onPress={() => go('tickets')} disabled={liveTrip.occupancy === 'FULL'} />
                <BigButton icon="qr-code" label={a('scanQr')} color="#C2185B" onPress={() => go('scanner')} />
                <BigButton icon="time" label={a('cdTripHistory')} color="#44506A" onPress={() => go('trip')} />
                <BigButton icon="stop-circle" label={a('endTrip')} color="#B3141B" onPress={() => trip(false)} loading={tripBusy} />
              </View>
            )}
          </>
        );
      case 'tickets':
        return liveTrip ? (
          <>
            <PassengerCounter trip={liveTrip} status={counter.status} lastUpdated={counter.lastUpdated} size="compact" />
            <IssueTicketPanel trip={liveTrip} startOpen />
          </>
        ) : (
          <>{counterCard}{startTripControls}</>
        );
      case 'scanner':
        return (
          <>
            {result && rs ? (
              <View style={[styles.result, { backgroundColor: rs.bg }]} accessibilityLiveRegion="assertive">
                <Text style={[styles.resultTitle, { color: rs.fg }]}>{a(('result' + result.result) as any) || result.display}</Text>
                <Text style={[styles.resultDetail, { color: rs.fg }]}>{result.detail}</Text>
                {result.ticket ? (
                  <View style={{ marginTop: SPACING.sm }}>
                    {result.ticket.passenger_name ? <Row label={a('passenger')} value={result.ticket.passenger_name} /> : null}
                    <Row label={a('route')} value={result.ticket.route} />
                    <Row label={a('journey')} value={`${result.ticket.from_stop} → ${result.ticket.to_stop}`} />
                    <Row label={a('passengers')} value={String(result.ticket.passenger_count)} />
                    <Row label={a('fare')} value={`₹${result.ticket.fare}`} />
                    <Row label={a('fareCategory')} value={`${result.ticket.fare_category === 'CHILD' ? a('catChild') : result.ticket.fare_category === 'SENIOR' ? a('catSenior') : a('catAdult')}${result.ticket.fare_stage ? ` · ${a('kmStage', { km: result.ticket.distance_km, stage: result.ticket.fare_stage })}` : ''}`} />
                    <Row label={a('eligibility')} value={String(result.ticket.eligibility || 'REGULAR_PAID').replace(/_/g, ' ')} />
                    <Row label={a('ticketId')} value={result.ticket.reference} />
                  </View>
                ) : null}
              </View>
            ) : null}
            {scanning ? (
              <TicketQrScanner onScan={verify} onClose={() => setScanning(false)} />
            ) : (
              <>
                <BigButton icon="qr-code" label={a('scanQr')} color="#C2185B" onPress={() => { setResult(null); setScanning(true); }} loading={busy} />
                <Card title={a('validateManually')}>
                  <TextInput style={styles.input} value={manual} onChangeText={setManual} placeholder={a('pasteQr')} placeholderTextColor={COLORS.textMuted}
                    multiline autoCapitalize="none" accessibilityLabel={a('pasteQr')} />
                  <AuthButton variant="secondary" label={a('validateTicket')} onPress={() => verify(manual)} disabled={manual.trim().length < 10} />
                </Card>
              </>
            )}
            <Card title={a('tripHistory')}>
              {me.history.length === 0 ? <Text style={accessStyles.muted}>{a('noScans')}</Text> : null}
              {me.history.map((h: any, i: number) => (
                <Row key={i} label={new Date(h.at).toLocaleTimeString()} value={`${a(('result' + h.result) as any) || h.result}${h.detail ? ` — ${h.detail}` : ''}`} />
              ))}
            </Card>
          </>
        );
      case 'trip':
        return (
          <>
            <Card title={a('currentTrip')}>
              {me.current_trip ? (
                <>
                  {me.current_trip.trip_code ? <Row label={a('rtTrip')} value={me.current_trip.trip_code} /> : null}
                  <Row label={a('route')} value={me.current_trip.route || '—'} />
                  <Row label={a('startedAt')} value={new Date(me.current_trip.started_at).toLocaleTimeString()} />
                  <Row label={a('passengers')} value={liveTrip ? `${liveTrip.passenger_count} / ${liveTrip.max_capacity}` : '—'} />
                  <Row label={a('ticketsScanned')} value={String(me.current_trip.tickets_scanned)} />
                  <BigButton icon="stop-circle" label={a('endTrip')} color="#B3141B" onPress={() => trip(false)} loading={tripBusy} />
                </>
              ) : startTripControls}
            </Card>
            <Card title={a('cdTripsTitle')}>
              {history === null ? <Loading lines={2} /> : history.length === 0 ? <Text style={accessStyles.muted}>{a('cdNoHistory')}</Text> : null}
              {(history || []).map(h => (
                <View key={h.trip_id} style={styles.histRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.histCode}>{h.trip_code || h.trip_id.slice(0, 8)}</Text>
                    <Text style={accessStyles.muted}>{h.started_at ? new Date(h.started_at).toLocaleString() : ''} · {h.status === 'ACTIVE' ? a('rtLive') : a('rtTripEnded')}</Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.histCount}>{h.passenger_count}/{h.max_capacity}</Text>
                    <Text style={accessStyles.muted}>{a('rtRevenue')} ₹{h.revenue}</Text>
                  </View>
                </View>
              ))}
            </Card>
          </>
        );
      default:
        return (
          <>
            <Card title={a('assignment')} right={me.bus ? <StatusBadge status={me.bus.operational_status} /> : undefined}>
              <Row label={a('busLabel')} value={me.bus?.fleet_label || a('notAssigned')} />
              <Row label={a('registrationNumber')} value={me.bus?.registration_number || a('notSet')} />
              <Row label={a('assignedRoute')} value={me.assigned_route || a('notAssigned')} />
              <Row label={a('admitted24h')} value={String(me.passengers_admitted_24h)} />
            </Card>
            <Card title={a('liveLocation')}>
              {!live ? (
                <Loading lines={1} />
              ) : live.realtime?.available ? (
                <>
                  <Row label={a('status')} value={live.realtime.status} />
                  <Row label={a('currentStop')} value={live.realtime.current_stop || '—'} />
                  <Row label={a('nextStop')} value={live.realtime.next_stop || '—'} />
                  <Row label={a('towards')} value={live.realtime.destination || '—'} />
                  <Row label={a('lastUpdate')} value={live.realtime.age_seconds != null ? a('secondsAgo', { s: live.realtime.age_seconds }) : '—'} />
                  <Text style={accessStyles.muted}>{a('bmtcFeedSource')}</Text>
                </>
              ) : (
                <View style={styles.unavailable}>
                  <Text style={styles.unavailableTitle}>REALTIME DATA UNAVAILABLE</Text>
                  {live.realtime?.reason ? <Text style={styles.unavailableBody}>{live.realtime.reason}</Text> : null}
                </View>
              )}
            </Card>
            <AuthButton variant="link" icon="log-out-outline" label={a('signOut')} onPress={() => AccessApi.logout()} />
          </>
        );
    }
  };

  return (
    <AuthScreen title={a('conductorDashboard')} subtitle={`${me.name} · ${me.employee_id}`} showBack={false}
      sidebar={<SideNav items={NAV} active={section} onSelect={go} />}
      bottomBar={<BottomNav items={NAV} active={section} onSelect={go} />}>
      <ErrorText text={error} />
      {body()}
    </AuthScreen>
  );
}

/** Cash ticket on board. The server prices it, checks capacity under a lock and counts it; nothing is counted here. */
function IssueTicketPanel({ trip, startOpen = false }: { trip: { trip_id: string; route: string | null; direction: number | null; occupancy: string; seats_left: number }; startOpen?: boolean }) {
  const { a } = useAccessT();
  const [open, setOpen] = useState(startOpen);
  const [stops, setStops] = useState<NetworkStop[] | null>(null);
  const [fromIdx, setFromIdx] = useState<number | null>(null);
  const [toIdx, setToIdx] = useState<number | null>(null);
  const [count, setCount] = useState(1);
  const [category, setCategory] = useState<'ADULT' | 'CHILD' | 'SENIOR'>('ADULT');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const key = useRef<string | null>(null);

  useEffect(() => {
    if (!open || stops || !trip.route) return;
    NetworkApi.routeStops(trip.route, trip.direction ?? 0).then(setStops).catch(e => setMsg({ ok: false, text: e.message }));
  }, [open, stops, trip.route, trip.direction]);
  // a changed selection is a new sale (new idempotency key); a retry of the same tap keeps the key
  useEffect(() => {
    key.current = null;
  }, [fromIdx, toIdx, count, category]);

  const full = trip.occupancy === 'FULL';
  const issue = async () => {
    if (!stops || fromIdx == null || toIdx == null) return;
    setBusy(true);
    setMsg(null);
    try {
      if (!key.current) key.current = newIdempotencyKey('cash');
      const t = await AccessApi.conductorIssue({ from_stop_id: stops[fromIdx].id, to_stop_id: stops[toIdx].id, passenger_count: count,
        fare_category: category, idempotency_key: key.current });
      key.current = null;
      setMsg({ ok: true, text: a('rtIssued', { ref: t.reference, fare: t.fare }) });
      haptic.success();
      setToIdx(null);
      setCount(1);
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
      haptic.error();
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return <AuthButton icon="ticket-outline" label={a('rtIssueTicket')} onPress={() => setOpen(true)} disabled={full} />;
  }
  return (
    <Card title={a('rtCashTicket')} right={<TouchableOpacity onPress={() => setOpen(false)} accessibilityRole="button" accessibilityLabel={a('cancel')} style={styles.closeBtn}><Text style={styles.closeText}>✕</Text></TouchableOpacity>}>
      {!stops ? <Text style={accessStyles.muted}>{a('rtStopsLoading')}</Text> : (
        <>
          <Text style={styles.pickLabel}>{a('from')}</Text>
          <ScrollView style={styles.stopList} nestedScrollEnabled>
            {stops.slice(0, -1).map((s, i) => (
              <TouchableOpacity key={s.id + i} onPress={() => { setFromIdx(i); if (toIdx != null && toIdx <= i) setToIdx(null); }}
                style={[styles.stop, fromIdx === i && styles.stopOn]} accessibilityRole="radio" accessibilityState={{ selected: fromIdx === i }}>
                <Text style={[styles.stopText, fromIdx === i && styles.stopTextOn]} numberOfLines={1}>{s.name}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <Text style={styles.pickLabel}>{a('to')}</Text>
          <ScrollView style={styles.stopList} nestedScrollEnabled>
            {fromIdx == null ? null : stops.map((s, i) => (i > fromIdx ? (
              <TouchableOpacity key={s.id + i} onPress={() => setToIdx(i)} style={[styles.stop, toIdx === i && styles.stopOn]}
                accessibilityRole="radio" accessibilityState={{ selected: toIdx === i }}>
                <Text style={[styles.stopText, toIdx === i && styles.stopTextOn]} numberOfLines={1}>{s.name}</Text>
              </TouchableOpacity>
            ) : null))}
          </ScrollView>
          <Text style={styles.pickLabel}>{a('passengers')}</Text>
          <View style={styles.stepper}>
            <TouchableOpacity style={styles.stepBtn} onPress={() => setCount(c => Math.max(1, c - 1))} accessibilityRole="button" accessibilityLabel="−"><Text style={styles.stepText}>−</Text></TouchableOpacity>
            <Text style={styles.stepValue}>{count}</Text>
            <TouchableOpacity style={styles.stepBtn} onPress={() => setCount(c => Math.min(6, Math.min(trip.seats_left || 1, c + 1)))} accessibilityRole="button" accessibilityLabel="+"><Text style={styles.stepText}>+</Text></TouchableOpacity>
          </View>
          <Choice options={[{ value: 'ADULT', label: a('catAdult') }, { value: 'CHILD', label: a('catChild') }, { value: 'SENIOR', label: a('catSenior') }]}
            value={category} onChange={v => setCategory(v as any)} />
          <Text style={accessStyles.muted}>{a('rtIssueQuote')}</Text>
        </>
      )}
      {msg ? <Text style={[styles.issueMsg, { color: msg.ok ? '#0F7A3A' : '#B3141B' }]} accessibilityLiveRegion="polite">{msg.text}</Text> : null}
      {full ? <Text style={[styles.issueMsg, { color: '#B3141B' }]}>{a('rtBusFull')}</Text> : null}
      <AuthButton icon="cash-outline" label={a('rtIssueTicket')} onPress={issue} loading={busy}
        disabled={full || fromIdx == null || toIdx == null || count > trip.seats_left} />
    </Card>
  );
}

const styles = StyleSheet.create({
  big: { flexGrow: 1, flexBasis: '46%', minHeight: 76, borderRadius: 18, alignItems: 'center', justifyContent: 'center', gap: 6,
    paddingHorizontal: SPACING.sm, marginBottom: SPACING.sm },
  bigText: { color: '#FFFFFF', fontSize: 16, fontWeight: '900', textAlign: 'center' },
  bigGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm },
  busHead: { marginBottom: SPACING.sm },
  busRoute: { fontSize: 32, fontWeight: '900', color: COLORS.deepNavy },
  busMeta: { fontSize: 14, fontWeight: '700', color: COLORS.textSecondary },
  noTrip: { fontSize: 18, fontWeight: '900', color: COLORS.textPrimary, marginBottom: 4 },
  histRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  histCode: { fontWeight: '900', color: COLORS.textPrimary },
  histCount: { fontWeight: '900', fontSize: 16, color: COLORS.deepNavy },
  closeBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  closeText: { fontSize: 18, fontWeight: '800', color: COLORS.textSecondary },
  pickLabel: { fontSize: 13, fontWeight: '800', color: COLORS.textSecondary, marginTop: SPACING.sm, marginBottom: 4 },
  stopList: { maxHeight: 180, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  stop: { minHeight: 44, justifyContent: 'center', paddingHorizontal: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  stopOn: { backgroundColor: COLORS.lightBlue },
  stopText: { fontSize: 15, color: COLORS.textPrimary },
  stopTextOn: { fontWeight: '800', color: COLORS.primaryDark },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: SPACING.sm },
  stepBtn: { width: 52, height: 52, borderRadius: 26, backgroundColor: COLORS.lightBlue, alignItems: 'center', justifyContent: 'center' },
  stepText: { fontSize: 26, fontWeight: '900', color: COLORS.primaryDark },
  stepValue: { fontSize: 28, fontWeight: '900', minWidth: 36, textAlign: 'center', color: COLORS.textPrimary },
  issueMsg: { fontSize: 15, fontWeight: '800', marginVertical: SPACING.sm },
  result: { borderRadius: RADIUS.lg, padding: SPACING.lg, marginBottom: SPACING.md },
  resultTitle: { fontSize: 24, fontWeight: '900' },
  resultDetail: { fontSize: 14, marginTop: 4 },
  unavailable: { backgroundColor: '#EEF0F4', borderRadius: RADIUS.md, padding: SPACING.md },
  unavailableTitle: { fontWeight: '900', color: '#44506A', fontSize: 15 },
  unavailableBody: { color: '#44506A', fontSize: 13, marginTop: 4 },
  input: { minHeight: 80, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.sm, textAlignVertical: 'top' },
});
