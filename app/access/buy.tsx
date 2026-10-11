import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { Card, Choice, DevBanner, ErrorText, Row, useAccessGuard } from '../../components/access/AccessUi';
import { CameraCapture } from '../../components/access/CameraCapture';
import { distanceMeters, positionIfGranted, requestPosition } from '../../components/access/location';
import { PassengerCounter } from '../../components/access/PassengerCounter';
import { useLiveTrips } from '../../hooks/useLiveTrips';
import { AccessApi, newIdempotencyKey, PickedFile, RecentJourney } from '../../services/accessApi';
import { normRoute } from '../../services/realtime';
import { NetworkApi } from '../../services/networkApi';
import { NetworkRouteDetail, NetworkRouteSummary, NetworkStop } from '../../types/network';

type FaceStep = 'NONE' | 'CONSENT' | 'CAMERA' | 'DEV_OUTCOME';

/**
 * Buy a ticket on any BMTC route: route → direction → from/to → passengers → server quote.
 * Faster paths: prefilled route/bus from the map, "Buy again" recent journeys, nearest stop, stop search.
 */
export default function BuyTicket() {
  const router = useRouter();
  const { a } = useAccessT();
  const params = useLocalSearchParams<{ route?: string; direction?: string; vehicle?: string }>();
  const { ready } = useAccessGuard(['PASSENGER', 'STUDENT']);
  const [me, setMe] = useState<any>(null);
  const [recent, setRecent] = useState<RecentJourney[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NetworkRouteSummary[]>([]);
  const [route, setRoute] = useState<NetworkRouteDetail | null>(null);
  const [direction, setDirection] = useState(0);
  const [stops, setStops] = useState<NetworkStop[]>([]);
  const [fromIdx, setFromIdx] = useState<number | null>(null);
  const [toIdx, setToIdx] = useState<number | null>(null);
  const [pending, setPending] = useState<{ from: string; to: string } | null>(null);
  const [fromFilter, setFromFilter] = useState('');
  const [toFilter, setToFilter] = useState('');
  const [nearest, setNearest] = useState<number | null>(null);
  const [count, setCount] = useState(1);
  const [category, setCategory] = useState<'ADULT' | 'CHILD' | 'SENIOR'>('ADULT');
  // Category prices from the last successful quote for THIS route + stops (cleared when the journey changes)
  const [lastFares, setLastFares] = useState<{ key: string; fares: Record<string, number> } | null>(null);
  const [useElig, setUseElig] = useState(false);
  const [faceId, setFaceId] = useState<string | null>(null);
  const [faceStep, setFaceStep] = useState<FaceStep>('NONE');
  const [capture, setCapture] = useState<PickedFile | null>(null);
  const [faceMsg, setFaceMsg] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null);
  const [quote, setQuote] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const vehicle = typeof params.vehicle === 'string' ? params.vehicle : undefined;
  // Running trips on this route with their live counts (from the backend; never counted here)
  const live = useLiveTrips(route ? `route:${normRoute(route.routeNumber)}` : null);
  const [tripId, setTripId] = useState<string | null>(null);
  const attemptKey = useRef<string | null>(null);
  useEffect(() => {
    const ids = live.trips.map(t => t.trip_id);
    if (tripId && ids.includes(tripId)) return;
    const byVehicle = vehicle ? live.trips.find(t => normRoute(t.vehicle_number) === normRoute(vehicle)) : undefined;
    setTripId(byVehicle?.trip_id ?? (live.trips.length === 1 ? live.trips[0].trip_id : null));
  }, [live.trips, vehicle, tripId]);
  const selectedTrip = live.trips.find(t => t.trip_id === tripId) || null;

  useEffect(() => {
    if (!ready) return;
    AccessApi.me().then(setMe).catch(() => undefined);
    AccessApi.recentJourneys().then(setRecent);
  }, [ready]);

  const openRoute = (routeNumber: string, dir = 0, preset?: { from: string; to: string }) =>
    NetworkApi.route(routeNumber)
      .then(d => {
        setRoute(d);
        setDirection(dir);
        setPending(preset || null);
        setQuery('');
        setResults([]);
      })
      .catch(e => setError(e.message));

  // Prefill from the map / route page
  useEffect(() => {
    if (ready && typeof params.route === 'string' && params.route) openRoute(params.route, Number(params.direction || 0) || 0);
  }, [ready, params.route]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const q = query.trim();
    if (!q || route) return setResults([]);
    const h = setTimeout(() => NetworkApi.searchRoutes(q, 20).then(r => setResults(r.routes)).catch(e => setError(e.message)), 300);
    return () => clearTimeout(h);
  }, [query, route]);

  // Load stops for the direction; apply a "Buy again" preset or the nearest stop
  useEffect(() => {
    if (!route) return;
    setFromIdx(null);
    setToIdx(null);
    setNearest(null);
    setFromFilter('');
    setToFilter('');
    let alive = true;
    NetworkApi.routeStops(route.routeNumber, direction)
      .then(async list => {
        if (!alive) return;
        setStops(list);
        if (pending) {
          const f = list.findIndex(s => s.id === pending.from);
          const t = list.findIndex(s => s.id === pending.to);
          if (f >= 0 && t > f) {
            setFromIdx(f);
            setToIdx(t);
          }
          setPending(null);
          return;
        }
        const pos = await positionIfGranted();
        if (pos && alive) pickNearest(list, pos);
      })
      .catch(e => setError(e.message));
    return () => {
      alive = false;
    };
  }, [route, direction]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickNearest = (list: NetworkStop[], pos: { latitude: number; longitude: number }) => {
    let best = -1;
    let bestD = Infinity;
    list.slice(0, -1).forEach((s, i) => {
      if (s.latitude == null || s.longitude == null) return;
      const d = distanceMeters(pos, { latitude: s.latitude, longitude: s.longitude });
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    if (best >= 0 && bestD <= 2000) {
      setFromIdx(best);
      setToIdx(null);
      setNearest(bestD);
    }
  };

  const from = fromIdx != null ? stops[fromIdx] : null;
  const to = toIdx != null ? stops[toIdx] : null;
  const journey = useMemo(
    () =>
      route && from && to
        ? { route: route.routeNumber, direction, from_stop_id: from.id, to_stop_id: to.id, passenger_count: count,
            use_eligibility: useElig, face_verification_id: useElig ? faceId : null, vehicle_number: vehicle,
            fare_category: useElig ? 'ADULT' : category, trip_id: tripId }
        : null,
    [route, from, to, direction, count, useElig, faceId, vehicle, category, tripId]
  );
  // A new purchase attempt (new idempotency key) whenever the journey changes; retries of a tap reuse it
  useEffect(() => {
    attemptKey.current = null;
  }, [journey]);

  useEffect(() => {
    if (!journey) return setQuote(null);
    let alive = true;
    AccessApi.quote(journey).then(q => alive && (setQuote(q), setError(null), setLastFares(q.fares_by_category ? { key: `${journey.route}|${journey.from_stop_id}|${journey.to_stop_id}`, fares: q.fares_by_category } : null))).catch(e => alive && (setQuote(null), setError(e.message)));
    return () => {
      alive = false;
    };
  }, [journey]);

  const runFace = async (outcome?: 'MATCH' | 'NO_MATCH', file?: PickedFile) => {
    const img = file || capture;
    if (!img) return;
    setBusy(true);
    try {
      const r = await AccessApi.faceVerify(img, outcome);
      setCapture(null);
      setFaceStep('NONE');
      setFaceId(r.result === 'MATCH' ? r.face_verification_id : null);
      setFaceMsg({ tone: r.result === 'MATCH' ? 'success' : 'warning', text: r.message });
    } catch (e: any) {
      setFaceMsg({ tone: 'warning', text: e.message });
      setFaceStep('NONE');
    } finally {
      setBusy(false);
    }
  };

  const buy = async () => {
    if (!journey || !from || !to || !route) return;
    setBusy(true);
    setError(null);
    try {
      if (!attemptKey.current) attemptKey.current = newIdempotencyKey('buy');
      const t = await AccessApi.createTicket({ ...journey, idempotency_key: attemptKey.current });
      attemptKey.current = null;
      await AccessApi.rememberJourney({ route: route.routeNumber, direction, from_stop_id: from.id, from_stop: from.name, to_stop_id: to.id, to_stop: to.name });
      router.replace({ pathname: '/access/ticket', params: { id: t.ticket_id } } as any);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const devFace = me?.passenger?.identity_is_development;
  const eligibilityPossible = me?.passenger?.identity_status === 'VERIFIED' || me?.student?.status === 'APPROVED';

  if (faceStep !== 'NONE') {
    return (
      <AuthScreen title={a('identityVerification')}>
        {devFace ? <DevBanner /> : null}
        {faceStep === 'CONSENT' ? (
          <>
            <Card>
              <Text style={styles.body}>
                {a('faceConsent')}
                {'\n\n'}
                {a('faceCamera')}
              </Text>
            </Card>
            <AuthButton icon="scan-outline" label={a('startFace')} onPress={() => setFaceStep('CAMERA')} />
            <AuthButton variant="secondary" label={a('cancel')} onPress={() => setFaceStep('NONE')} />
          </>
        ) : faceStep === 'CAMERA' ? (
          <CameraCapture
            facing="front"
            purpose={a('faceCameraPurpose')}
            captureLabel={a('capture')}
            onCaptured={f => {
              setCapture(f);
              if (devFace) setFaceStep('DEV_OUTCOME');
              else runFace(undefined, f);
            }}
            onCancel={() => setFaceStep('NONE')}
          />
        ) : (
          <>
            <Notice tone="demo" title={a('devFaceTitle')} body={a('devFaceBody')} />
            <AuthButton label={a('simulateMatch')} onPress={() => runFace('MATCH')} loading={busy} />
            <AuthButton variant="secondary" label={a('simulateNoMatch')} onPress={() => runFace('NO_MATCH')} />
          </>
        )}
      </AuthScreen>
    );
  }

  const fares = journey && lastFares?.key === `${journey.route}|${journey.from_stop_id}|${journey.to_stop_id}` ? lastFares.fares : null;
  const footer = quote ? (
    <View>
      <View style={styles.footerRow}>
        <Text style={styles.footerJourney} numberOfLines={1}>
          {quote.route} · {quote.from_stop.name} → {quote.to_stop.name}
        </Text>
        <Text style={styles.footerFare}>₹{quote.fare}</Text>
      </View>
      <AuthButton
        icon={quote.fare === 0 ? 'qr-code-outline' : 'card-outline'}
        label={quote.fare === 0 ? a('getFreeTicket') : a('buyFor', { fare: quote.fare })}
        onPress={buy}
        loading={busy}
        disabled={(useElig && !quote.eligible) || !selectedTrip || selectedTrip.occupancy === 'FULL' || selectedTrip.seats_left < count}
      />
      {selectedTrip?.occupancy === 'FULL' ? <Text style={styles.fullNote}>{a('rtBusFull')}</Text> : null}
      {useElig && !quote.eligible ? (
        <AuthButton variant="link" label={a('buyRegularInstead', { fare: quote.normal_fare })} onPress={() => setUseElig(false)} />
      ) : null}
    </View>
  ) : undefined;

  const filteredFrom = stops.slice(0, -1).map((s, i) => ({ s, i })).filter(x => !fromFilter || x.s.name.toLowerCase().includes(fromFilter.toLowerCase()));
  const filteredTo =
    fromIdx == null ? [] : stops.map((s, i) => ({ s, i })).filter(x => x.i > fromIdx && (!toFilter || x.s.name.toLowerCase().includes(toFilter.toLowerCase())));

  return (
    <AuthScreen title={a('buyTitle')} subtitle={a('buySub')} footer={footer}>
      {!route && recent.length ? (
        <Card title={a('recentJourneys')}>
          {recent.map(r => (
            <TouchableOpacity key={`${r.route}-${r.from_stop_id}-${r.to_stop_id}`} style={styles.recent}
              onPress={() => openRoute(r.route, r.direction, { from: r.from_stop_id, to: r.to_stop_id })}
              accessibilityRole="button" accessibilityLabel={`${r.route} ${r.from_stop} ${r.to_stop}`}>
              <Ionicons name="refresh" size={16} color={COLORS.primaryDark} />
              <Text style={styles.routeNo}>{r.route}</Text>
              <Text style={styles.routeName} numberOfLines={1}>{r.from_stop} → {r.to_stop}</Text>
            </TouchableOpacity>
          ))}
        </Card>
      ) : null}

      <Card title={a('stepRoute')}>
        {route ? (
          <View style={styles.routeRow}>
            <Text style={styles.routeNo}>{route.routeNumber}</Text>
            <Text style={styles.routeName} numberOfLines={2}>{route.origin} ⇄ {route.destination}</Text>
            <TouchableOpacity onPress={() => { setRoute(null); setStops([]); setQuote(null); }} accessibilityRole="button" accessibilityLabel={a('change')} style={styles.changeBtn}>
              <Text style={styles.link}>{a('change')}</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            <TextInput style={styles.search} value={query} onChangeText={setQuery} placeholder={a('searchRoute')} autoCapitalize="characters"
              placeholderTextColor={COLORS.textMuted} accessibilityLabel="Search route" />
            {results.map(r => (
              <TouchableOpacity key={r.id} style={styles.result} onPress={() => openRoute(r.routeNumber)} accessibilityRole="button" accessibilityLabel={`Route ${r.routeNumber}`}>
                <Text style={styles.routeNo}>{r.routeNumber}</Text>
                <Text style={styles.routeName} numberOfLines={1}>{r.origin} ⇄ {r.destination}</Text>
              </TouchableOpacity>
            ))}
          </>
        )}
      </Card>

      {route ? (
        <Card title={live.trips.length > 1 ? a('rtChooseBus') : a('rtRunningBuses')}>
          {live.loaded && live.trips.length === 0 ? <Notice tone="info" body={a('rtNoActiveTrip')} /> : null}
          {live.trips.map(t => (
            <TouchableOpacity key={t.trip_id} onPress={() => setTripId(t.trip_id)} accessibilityRole="radio"
              accessibilityState={{ selected: t.trip_id === tripId }} accessibilityLabel={`${t.bus_label || t.trip_code}`}
              style={[styles.tripPick, t.trip_id === tripId && styles.tripPickOn]}>
              <PassengerCounter trip={t} status={live.status} lastUpdated={live.lastUpdated} size="compact" />
            </TouchableOpacity>
          ))}
        </Card>
      ) : null}

      {route ? (
        <Card title={a('stepStops')}>
          <Choice
            options={(route.directions || []).map(d => ({ value: String(d.direction), label: a('towards', { place: d.destinationName || '' }) }))}
            value={String(direction)}
            onChange={v => setDirection(Number(v))}
          />
          <View style={styles.labelRow}>
            <Text style={styles.label}>{a('from')}{from ? `: ${from.name}` : ''}</Text>
            <TouchableOpacity onPress={async () => { const p = await requestPosition(); if (p) pickNearest(stops, p); }} accessibilityRole="button" accessibilityLabel="Nearest stop">
              <Text style={styles.link}>📍</Text>
            </TouchableOpacity>
          </View>
          {nearest != null && from ? <Text style={styles.hint}>{a('nearestStop', { m: nearest })}</Text> : null}
          <TextInput style={styles.filter} value={fromFilter} onChangeText={setFromFilter} placeholder={a('findStop')} placeholderTextColor={COLORS.textMuted} accessibilityLabel={`${a('from')} ${a('findStop')}`} />
          <StopList items={filteredFrom} selected={fromIdx} onSelect={i => { setFromIdx(i); setToIdx(null); setNearest(null); }} />
          {fromIdx != null ? (
            <>
              <Text style={[styles.label, { marginTop: SPACING.md }]}>{a('to')}{to ? `: ${to.name}` : ''}</Text>
              <TextInput style={styles.filter} value={toFilter} onChangeText={setToFilter} placeholder={a('findStop')} placeholderTextColor={COLORS.textMuted} accessibilityLabel={`${a('to')} ${a('findStop')}`} />
              <StopList items={filteredTo} selected={toIdx} onSelect={setToIdx} />
            </>
          ) : null}
        </Card>
      ) : null}

      {journey ? (
        <Card title={a('stepFare')}>
          <View style={styles.qtyRow}>
            <Text style={styles.label}>{a('passengers')}</Text>
            <View style={styles.qty}>
              <TouchableOpacity style={styles.qtyBtn} onPress={() => setCount(Math.max(1, count - 1))} accessibilityRole="button" accessibilityLabel={a('fewerPassengers')}><Ionicons name="remove" size={20} /></TouchableOpacity>
              <Text style={styles.qtyText} accessibilityLiveRegion="polite">{count}</Text>
              <TouchableOpacity style={styles.qtyBtn} onPress={() => setCount(Math.min(6, count + 1))} accessibilityRole="button" accessibilityLabel={a('morePassengers')}><Ionicons name="add" size={20} /></TouchableOpacity>
            </View>
          </View>
          {!useElig ? (
            <>
              <Text style={styles.label}>{a('fareCategory')}</Text>
              <Choice
                options={[
                  { value: 'ADULT', label: fares ? `${a('catAdult')} ₹${fares.ADULT}` : a('catAdult') },
                  { value: 'CHILD', label: fares ? `${a('catChild')} ₹${fares.CHILD}` : a('catChild') },
                  { value: 'SENIOR', label: fares ? `${a('catSenior')} ₹${fares.SENIOR}` : a('catSenior') },
                ]}
                value={category}
                onChange={v => setCategory(v as any)}
              />
              {category === 'CHILD' ? <Text style={styles.small}>{a('childNote')}</Text> : null}
              {category === 'SENIOR' ? <Text style={styles.small}>{a('seniorNote')}</Text> : null}
            </>
          ) : null}
          {me?.passenger?.gender === 'FEMALE' || me?.role === 'STUDENT' ? (
            <View style={styles.switchRow}>
              <Text style={styles.label}>{a('useEligibility')}</Text>
              <Switch value={useElig} onValueChange={v => { setUseElig(v); setFaceMsg(null); }} accessibilityLabel="Use verified eligibility" />
            </View>
          ) : null}
          {useElig && !eligibilityPossible ? <Notice tone="info" body={a('noEligibilityYet')} /> : null}
          {faceMsg ? <Notice tone={faceMsg.tone} body={faceMsg.text} /> : null}
          {quote ? (
            <>
              {quote.distance_km != null ? (
                <Row label={a('distanceStage')} value={quote.fare_stage ? a('kmStage', { km: quote.distance_km, stage: quote.fare_stage }) : `${quote.distance_km} km`} />
              ) : null}
              <Row label={a('normalFare')} value={`₹${quote.normal_fare}`} />
              <Row label={a('yourFare')} value={`₹${quote.fare}`} bold />
              {quote.eligible ? <Row label={a('eligibility')} value={quote.eligibility_type} /> : null}
              {useElig && !quote.eligible ? quote.eligibility_reasons.map((r: string) => <Text key={r} style={styles.reason}>• {r}</Text>) : null}
              <Text style={styles.small}>{quote.fare_source_note}</Text>
              {quote.eligibility_label ? <Text style={styles.devSmall}>{quote.eligibility_label}</Text> : null}
              {quote.eligible || useElig ? <Text style={styles.small}>{quote.policy_disclaimer}</Text> : null}
              {quote.fare > 0 ? <Text style={styles.small}>{quote.payment_label}</Text> : null}
              {useElig && quote.needs_face_verification ? (
                <AuthButton icon="scan-outline" label={a('verifyWithFace')} onPress={() => { setFaceMsg(null); setFaceStep('CONSENT'); }} />
              ) : null}
            </>
          ) : null}
        </Card>
      ) : null}
      <ErrorText text={error} />
    </AuthScreen>
  );
}

function StopList({ items, selected, onSelect }: { items: { s: NetworkStop; i: number }[]; selected: number | null; onSelect: (i: number) => void }) {
  return (
    <ScrollView style={styles.stops} nestedScrollEnabled>
      {items.map(({ s, i }) => (
        <TouchableOpacity key={`${s.id}-${i}`} style={[styles.stop, selected === i && styles.stopActive]} onPress={() => onSelect(i)}
          accessibilityRole="button" accessibilityLabel={s.name} accessibilityState={{ selected: selected === i }}>
          <Text style={[styles.stopText, selected === i && { fontWeight: '800', color: COLORS.deepNavy }]} numberOfLines={1}>{s.name}</Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { color: COLORS.textPrimary, fontSize: 15, lineHeight: 22 },
  search: { minHeight: 48, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, paddingHorizontal: SPACING.md, fontSize: 15, marginBottom: SPACING.sm },
  filter: { minHeight: 44, borderWidth: 1, borderColor: COLORS.borderSubtle, borderRadius: RADIUS.md, paddingHorizontal: SPACING.md, fontSize: 14, marginBottom: SPACING.xs || 4 },
  result: { flexDirection: 'row', alignItems: 'center', minHeight: 48, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle, gap: SPACING.sm },
  recent: { flexDirection: 'row', alignItems: 'center', minHeight: 48, gap: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  routeRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  routeNo: { backgroundColor: COLORS.deepNavy, color: COLORS.textInverse, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 4, borderRadius: RADIUS.sm, overflow: 'hidden' },
  routeName: { flex: 1, color: COLORS.textPrimary },
  changeBtn: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 4 },
  link: { color: COLORS.primaryDark, fontWeight: '800', fontSize: 16 },
  labelRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 44 },
  label: { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary, marginBottom: 4, flexShrink: 1 },
  hint: { fontSize: 12, color: '#0F5F30', marginBottom: 4 },
  tripPick: { borderRadius: 20, borderWidth: 2, borderColor: 'transparent', padding: 2, marginBottom: 6 },
  tripPickOn: { borderColor: COLORS.primary },
  fullNote: { color: '#B3141B', fontWeight: '800', textAlign: 'center', marginTop: 6 },
  stops: { maxHeight: 220, borderWidth: 1, borderColor: COLORS.borderSubtle, borderRadius: RADIUS.md },
  stop: { minHeight: 44, justifyContent: 'center', paddingHorizontal: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  stopActive: { backgroundColor: COLORS.lightBlue },
  stopText: { color: COLORS.textPrimary },
  qtyRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  qty: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  qtyBtn: { width: 44, height: 44, borderRadius: RADIUS.md, backgroundColor: COLORS.surfaceSubtle, alignItems: 'center', justifyContent: 'center' },
  qtyText: { fontSize: 18, fontWeight: '800' },
  switchRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 48 },
  reason: { color: '#7A4B00', fontSize: 13, marginTop: 2 },
  small: { color: COLORS.textMuted, fontSize: 12, marginTop: 6, lineHeight: 17 },
  devSmall: { color: '#B45309', fontSize: 12, fontWeight: '800', marginTop: 6 },
  footerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: SPACING.sm },
  footerJourney: { flex: 1, color: COLORS.textSecondary, fontSize: 13 },
  footerFare: { fontSize: 20, fontWeight: '900', color: COLORS.deepNavy },
});
