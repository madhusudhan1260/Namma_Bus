import React, { useCallback, useEffect, useState } from 'react';
import { Platform, Share, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { Card, DevBanner, ErrorText, Loading, OfflineBanner, Row, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { QRCodeView } from '../../components/QRCodeView';
import { PassengerCounter } from '../../components/access/PassengerCounter';
import { useLiveTrips } from '../../hooks/useLiveTrips';
import { AccessApi, AccessError } from '../../services/accessApi';

export default function TicketScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { ready } = useAccessGuard(['PASSENGER', 'STUDENT']);
  const [t, setT] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showQr, setShowQr] = useState(true);
  const [showDetails, setShowDetails] = useState(false);
  const [payCfg, setPayCfg] = useState<Awaited<ReturnType<typeof AccessApi.paymentConfig>> | null>(null);
  // Live passenger count of the trip this ticket belongs to (counts only, never other passengers' details)
  const live = useLiveTrips(t?.trip_id && !t?.offline ? `trip:${t.trip_id}` : null, { keepEnded: true });

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setT(await AccessApi.ticket(String(id)));
    } catch (e: any) {
      // Offline and this ticket was never opened: fall back to the cached ticket list
      if (e instanceof AccessError && e.status === 0) {
        try {
          const list = await AccessApi.tickets();
          const hit = list.tickets.find((x: any) => x.ticket_id === id);
          if (hit) return setT({ ...hit, offline: true, cached_at: (list as any).cached_at });
        } catch {
          /* fall through */
        }
      }
      setError(e.message);
    }
  }, [id]);
  useEffect(() => {
    if (ready) load();
  }, [ready, load]);
  useEffect(() => {
    if (t?.status === 'PENDING_PAYMENT' && !t.offline && !payCfg) AccessApi.paymentConfig().then(setPayCfg).catch(() => undefined);
  }, [t?.status, t?.offline, payCfg]);

  const cancelPayment = async () => {
    setBusy(true);
    try {
      await AccessApi.paymentCancel(t.ticket_id);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const share = () => {
    // A summary only — never the QR itself (the QR is the ticket; sharing it would let someone else travel on it)
    const msg = `ನಮ್ಮ BUS ${t.route} · ${t.from_stop} → ${t.to_stop} · ${t.fare === 0 ? a('jFree') : `₹${t.fare}`} · ${t.reference}`;
    Share.share({ message: msg }).catch(() => undefined);
  };

  const pay = async (outcome: 'SUCCESS' | 'FAILURE') => {
    setBusy(true);
    try {
      await AccessApi.payDemo(t.ticket_id, outcome);
      await load();
      AccessApi.tickets().catch(() => undefined); // refresh the offline copy
    } catch (e: any) {
      setError(e.message);
      load(); // e.g. bus filled up while paying → the server refunded; show the real state
    } finally {
      setBusy(false);
    }
  };

  if (!t) {
    return (
      <AuthScreen title={a('ticketTitle')}>
        <ErrorText text={error} />
        {error ? <AuthButton variant="secondary" label={a('tryAgain')} onPress={load} /> : <Loading />}
      </AuthScreen>
    );
  }

  const free = t.ticket_type === 'ELIGIBLE_FREE';
  const expired = t.status === 'ISSUED' && new Date(t.expires_at).getTime() <= Date.now();
  const displayStatus = t.payment_status === 'REFUNDED' ? 'REFUNDED' : expired ? 'EXPIRED' : t.status;
  const valid = t.status === 'ISSUED' && !expired;
  return (
    <AuthScreen title={a('ticketTitle')}>
      {t.offline ? <OfflineBanner at={t.cached_at} /> : null}
      {t.verification_reference?.includes('MOCK') ? <DevBanner /> : null}

      {/* The ticket */}
      <View style={[styles.ticket, valid && styles.ticketValid]} accessibilityLabel={`${t.route} ${t.from_stop} → ${t.to_stop}, ${a(('st' + displayStatus) as any)}`}>
        <View style={styles.ticketHead}>
          <Text style={styles.brand}>ನಮ್ಮ BUS</Text>
          <View style={[styles.statusPill, { backgroundColor: valid ? '#E3F6EA' : '#EEF0F4' }]}>
            <Text style={[styles.statusText, { color: valid ? '#0F7A3A' : '#44506A' }]}>{a(('st' + displayStatus) as any)}</Text>
          </View>
        </View>
        <Text style={styles.bigRoute}>{t.route}</Text>
        <Text style={styles.journey}>{t.from_stop} → {t.to_stop}</Text>
        <View style={styles.factRow}>
          {t.passenger_name ? <Fact label={a('passenger')} value={t.passenger_name} /> : null}
          <Fact label={a('fare')} value={t.fare === 0 ? a('jFree') : `₹${t.fare}`} />
          {t.trip?.trip_code ? <Fact label={a('rtTrip')} value={t.trip.trip_code} /> : null}
          <Fact label={a('rtIssuedAt')} value={new Date(t.issued_at || t.created_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })} />
        </View>
        {t.qr_payload && valid && showQr ? (
          <View style={styles.qr} accessible accessibilityLabel={`${a('ticketId')} ${t.reference}`}>
            <QRCodeView value={t.qr_payload} size={220} />
            <Text style={styles.ref}>{t.reference}</Text>
            <Text style={styles.qrNote}>{a('qrNote')}</Text>
            <Text style={styles.saved}>{a('savedOffline')}</Text>
            {t.payment_label ? <Text style={styles.demo}>{t.payment_label}</Text> : null}
          </View>
        ) : null}
        <View style={styles.actions}>
          {t.qr_payload && valid ? <Action icon="qr-code-outline" label={a('viewQr')} onPress={() => setShowQr(v => !v)} /> : null}
          <Action icon="information-circle-outline" label={a('ticketDetails')} onPress={() => setShowDetails(v => !v)} />
          {Platform.OS !== 'web' || typeof navigator !== 'undefined' && (navigator as any).share ? (
            <Action icon="share-outline" label={a('shareTicket')} onPress={share} />
          ) : null}
        </View>
      </View>

      {live.trip ? <PassengerCounter trip={live.trip} status={live.status} lastUpdated={live.lastUpdated} size="compact" /> : null}

      {t.status === 'PENDING_PAYMENT' && !t.offline ? (
        <Card title={a('payment')}>
          <Row label={a('amount')} value={`₹${t.fare}`} bold />
          {!payCfg ? <Loading lines={1} /> : !payCfg.configured ? (
            <Notice tone="warning" body={a('payConfigRequired')} />
          ) : payCfg.is_test ? (
            <>
              <Notice tone="demo" title="DEMO PAYMENT — NO REAL MONEY CHARGED" body={a('payDemoNotice')} />
              <AuthButton icon="card-outline" label={a('payDemo', { fare: t.fare })} onPress={() => pay('SUCCESS')} loading={busy} />
              <AuthButton variant="secondary" label={a('simulateFailedPayment')} onPress={() => pay('FAILURE')} />
            </>
          ) : (
            <Notice tone="info" body={payCfg.message || a('payConfigRequired')} />
          )}
          <AuthButton variant="link" icon="close-outline" label={a('payCancel')} onPress={cancelPayment} />
        </Card>
      ) : null}
      {t.status === 'CANCELLED' ? <Notice tone="warning" body={t.payment_status === 'REFUNDED' ? (error || a('nPAYMENT_REFUNDED_b', { fare: t.fare })) : t.payment_status === 'CANCELLED' ? a('stCANCELLED') : a('payFailedNoTicket')} /> : null}
      {t.status === 'USED' ? <Notice tone="info" body={a('ticketUsed')} /> : null}

      {showDetails ? (
      <Card title={a('ticketDetails')}>
        {t.passenger_name ? <Row label={a('passenger')} value={t.passenger_name} /> : null}
        <Row label={a('passengerId')} value={String(t.passenger_id).slice(0, 12).toUpperCase()} />
        <Row label={a('eligibility')} value={free ? <StatusBadge status="VERIFIED" /> : a('regularFare')} />
        {free ? <Row label={a('eligibilityType')} value={t.eligibility_type} /> : null}
        <Row label={a('route')} value={t.route} />
        {t.trip?.trip_code ? <Row label={a('rtTrip')} value={`${t.trip.trip_code}${t.trip.bus_label ? ` · ${t.trip.bus_label}` : ''}`} /> : null}
        <Row label={a('from')} value={t.from_stop} />
        <Row label={a('to')} value={t.to_stop} />
        <Row label={a('passengers')} value={String(t.passenger_count)} />
        <Row label={a('fareCategory')} value={t.fare_category === 'CHILD' ? a('catChild') : t.fare_category === 'SENIOR' ? a('catSenior') : a('catAdult')} />
        {t.fare_stage ? <Row label={a('distanceStage')} value={a('kmStage', { km: t.distance_km, stage: t.fare_stage })} /> : null}
        <Row label={a('dateTime')} value={new Date(t.created_at).toLocaleString()} />
        {t.issued_at ? <Row label={a('rtIssuedAt')} value={new Date(t.issued_at).toLocaleTimeString()} /> : null}
        <Row label={a('validUntil')} value={new Date(t.expires_at).toLocaleTimeString()} />
        {free && t.normal_fare ? <Row label={a('normalFare')} value={`₹${t.normal_fare}`} /> : null}
        <Row label={a('fare')} value={`₹${t.fare}`} bold />
        {free ? <Row label={a('identityVerificationLabel')} value={<StatusBadge status="VERIFIED" />} /> : null}
        {t.verification_reference ? <Row label={a('verificationRef')} value={t.verification_reference} /> : null}
        <Row label={a('ticketId')} value={t.reference} />
        <Row label={a('payment')} value={t.payment_status === 'NOT_REQUIRED' ? a('notRequired') : t.payment_status} />
        <Row label={a('status')} value={a(('st' + displayStatus) as any)} />
      </Card>
      ) : null}
      <AuthButton variant="secondary" label={a('myTickets')} onPress={() => router.replace('/access/tickets' as any)} />
      <AuthButton variant="link" label={a('backToDashboard')} onPress={() => router.replace('/(tabs)' as any)} />
    </AuthScreen>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.fact}>
      <Text style={styles.factLabel}>{label}</Text>
      <Text style={styles.factValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Action({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.action} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={18} color={COLORS.deepNavy} />
      <Text style={styles.actionText}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  ticket: { backgroundColor: '#FFFFFF', borderRadius: 20, padding: SPACING.lg, marginBottom: SPACING.md, borderWidth: 1, borderColor: COLORS.border,
    shadowColor: '#3B0A24', shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 3 },
  ticketValid: { borderColor: '#1FA855', borderWidth: 2 },
  ticketHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brand: { fontSize: 14, fontWeight: '900', color: '#C2185B', letterSpacing: 1 },
  statusPill: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 },
  statusText: { fontSize: 13, fontWeight: '900' },
  bigRoute: { fontSize: 34, fontWeight: '900', color: COLORS.deepNavy, marginTop: SPACING.sm },
  journey: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary, marginTop: 2 },
  factRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.md, marginTop: SPACING.md },
  fact: { minWidth: 90, flexGrow: 1 },
  factLabel: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '700' },
  factValue: { fontSize: 15, color: COLORS.textPrimary, fontWeight: '800', marginTop: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm, marginTop: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.borderSubtle, paddingTop: SPACING.md },
  action: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, paddingHorizontal: 14, borderRadius: 999, backgroundColor: COLORS.lightBlue },
  actionText: { fontWeight: '800', color: COLORS.deepNavy },
  qr: { alignItems: 'center', backgroundColor: '#FFFFFF', borderRadius: RADIUS.lg, paddingTop: SPACING.lg },
  ref: { fontSize: 18, fontWeight: '900', letterSpacing: 1, color: COLORS.deepNavy, marginTop: SPACING.sm },
  qrNote: { color: COLORS.textSecondary, fontSize: 12, textAlign: 'center', marginTop: SPACING.sm },
  saved: { color: '#0F5F30', fontSize: 12, fontWeight: '700', marginTop: 4, textAlign: 'center' },
  demo: { color: '#B45309', fontWeight: '800', fontSize: 12, marginTop: 6 },
});
