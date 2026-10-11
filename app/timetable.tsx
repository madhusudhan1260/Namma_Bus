import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { NetworkApi } from '../services/networkApi';
import { NetworkRouteSummary, NetworkStop } from '../types/network';
import { CITY_CENTRE, positionIfGranted } from '../components/access/location';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OriginDestination, OutlinedInput } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import NetworkMap from '../components/network/NetworkMap';
import { FadeIn, PressScale, Skeleton, stagger } from '../components/ui/motion';

type Timetable = Awaited<ReturnType<typeof NetworkApi.timetable>>;
const GREEN = '#1FBF7F';
const toMin = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
};
const nowMin = () => new Date().getHours() * 60 + new Date().getMinutes();

/** Departure board for one route (scheduled GTFS times), with the next departure highlighted. */
function Departures({ tt, compact = false }: { tt: Timetable; compact?: boolean }) {
  const { a } = useAccessT();
  const [dir, setDir] = useState(0);
  const d = tt.directions[dir];
  const now = nowMin();
  const next = d ? d.departures.findIndex(x => toMin(x) >= now) : -1;
  const list = d ? (compact ? d.departures.filter(x => toMin(x) >= now).slice(0, 8) : d.departures) : [];
  if (!tt.directions.length) return <Text style={styles.muted}>{a('ttNone')}</Text>;
  return (
    <View>
      {tt.directions.length > 1 ? (
        <View style={styles.dirRow}>
          {tt.directions.map((x, i) => (
            <PressScale key={x.direction} hoverLift={false} style={[styles.dirBtn, dir === i && styles.dirOn]} onPress={() => setDir(i)} accessibilityRole="radio" accessibilityState={{ selected: dir === i }}>
              <Text style={[styles.dirText, dir === i && { color: '#FFFFFF' }]} numberOfLines={1}>{a('ttTowards', { place: x.headsign || '—' })}</Text>
            </PressScale>
          ))}
        </View>
      ) : (
        <Text style={styles.towards}>{a('ttTowards', { place: d?.headsign || '—' })}</Text>
      )}
      <Text style={styles.from}>{a('ttFrom', { stop: d?.from || '—' })} · {a('ttCount', { n: d?.departures.length || 0 })}</Text>
      {next >= 0 ? <Text style={styles.next}>{a('ttNext', { time: d!.departures[next] })}</Text> : <Text style={styles.muted}>{a('ttNoMore')}</Text>}
      <View style={styles.grid}>
        {list.map((t, i) => {
          const past = toMin(t) < now;
          const isNext = d && d.departures[next] === t;
          return (
            <FadeIn key={t + i} delay={Math.min(i, 30) * 12} duration={240}>
              <View style={[styles.time, past && styles.timePast, isNext && styles.timeNext]}>
                <Text style={[styles.timeText, past && { color: '#AAA' }, isNext && { color: '#FFFFFF' }]}>{t}</Text>
              </View>
            </FadeIn>
          );
        })}
      </View>
    </View>
  );
}

/** Time Table: by stop (from → to, direct routes and their next scheduled departures) or by route. */
export default function TimetableScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const params = useLocalSearchParams<{ route?: string }>();
  const [tab, setTab] = useState<'STOP' | 'ROUTE'>(typeof params.route === 'string' && params.route ? 'ROUTE' : 'STOP');

  // map: nearby bus stops
  const [stops, setStops] = useState<NetworkStop[]>([]);
  const [focus, setFocus] = useState<{ latitude: number; longitude: number } | null>(null);
  useEffect(() => {
    positionIfGranted().then(p => {
      const o = p || CITY_CENTRE;
      NetworkApi.stopsNearby(o.latitude, o.longitude, 1200, 20).then(r => setStops(r.stops)).catch(() => setStops([]));
    });
  }, []);

  // by route
  const [query, setQuery] = useState(typeof params.route === 'string' ? params.route : '');
  const [routes, setRoutes] = useState<NetworkRouteSummary[] | null>(null);
  const [route, setRoute] = useState<string | null>(typeof params.route === 'string' && params.route ? params.route : null);
  const [tt, setTt] = useState<Timetable | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!route) return;
    setLoading(true);
    setTt(null);
    NetworkApi.timetable(route).then(setTt).catch(() => setTt({ source: '', route, directions: [] })).finally(() => setLoading(false));
  }, [route]);
  const findRoutes = async () => {
    if (!query.trim()) return;
    setRoute(null);
    setRoutes((await NetworkApi.searchRoutes(query.trim(), 12).catch(() => ({ routes: [] as NetworkRouteSummary[] }))).routes);
  };

  // by stop
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [byStop, setByStop] = useState<{ route: string; fromStop: string; toStop: string; next?: string | null; tt: Timetable | null }[] | null>(null);
  const searchByStop = async () => {
    if (from.trim().length < 2 || to.trim().length < 2) return;
    setBusy(true);
    setByStop(null);
    try {
      const r = await NetworkApi.journey(from.trim(), to.trim());
      const direct: { route: string; fromStop: string; toStop: string; next?: string | null }[] = [];
      for (const p of r.plans) {
        if (p.legs.length !== 1) continue;
        const l: any = p.legs[0];
        if (!direct.find(d => d.route === l.routeNumber)) direct.push({ route: l.routeNumber, fromStop: l.fromStop.name, toStop: l.toStop.name, next: l.nextDeparture });
        if (direct.length >= 5) break;
      }
      const tts = await Promise.all(direct.map(d => NetworkApi.timetable(d.route).catch(() => null)));
      setByStop(direct.map((d, i) => ({ ...d, tt: tts[i] })));
    } catch {
      setByStop([]);
    } finally {
      setBusy(false);
    }
  };

  const mapStops = useMemo(() => stops, [stops]);

  return (
    <FeatureShell
      title={a('tileTimetable')}
      icon="time-outline"
      color={GREEN}
      renderMap={mapType => (
        <NetworkMap vehicles={[]} selectedVehicleId={null} stops={mapStops} stopVariant="stand" mapType={mapType} focus={focus}
          onSelectStop={s => { setFocus({ latitude: s.latitude, longitude: s.longitude }); if (tab === 'STOP') setFrom(s.name); }} />
      )}
    >
      <View style={styles.tabs} accessibilityRole="tablist">
        {([['STOP', 'ttByStop'], ['ROUTE', 'ttByRoute']] as const).map(([k, l]) => (
          <PressScale key={k} hoverLift={false} style={[styles.tab, tab === k && styles.tabOn]} onPress={() => setTab(k)} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}>
            <Text style={[styles.tabText, tab === k && styles.tabTextOn]}>{a(l)}</Text>
          </PressScale>
        ))}
      </View>

      {tab === 'STOP' ? (
        <FadeIn key="stop">
          <OriginDestination from={from} to={to} setFrom={setFrom} setTo={setTo} fromLabel={a('fsEnterOrigin')} toLabel={a('fsEnterDestination')} swapLabel={a('planSwap')} />
          <View style={{ height: 14 }} />
          <GradientButton label={busy ? a('fsSearching') : a('fsSearch')} icon="search" onPress={searchByStop} busy={busy} disabled={from.trim().length < 2 || to.trim().length < 2} />
          {busy ? <View style={{ gap: 10, marginTop: 16 }}>{[0, 1].map(i => <Skeleton key={i} height={120} radius={14} />)}</View> : null}
          {byStop && !byStop.length ? <EmptyState compact title={a('fsNoDirectTitle')} message={a('fsNoDirectMsg')} /> : null}
          {byStop?.map((d, i) => (
            <FadeIn key={d.route} delay={stagger(i, 70)} style={styles.card}>
              <View style={styles.cardHead}>
                <Text style={styles.badge}>{d.route}</Text>
                <Text style={styles.cardTitle} numberOfLines={2}>{d.fromStop} → {d.toStop}</Text>
              </View>
              {d.tt ? <Departures tt={d.tt} compact /> : <Text style={styles.muted}>{a('ttNone')}</Text>}
              <PressScale hoverLift={false} style={styles.link} onPress={() => { setTab('ROUTE'); setQuery(d.route); setRoute(d.route); }} accessibilityRole="button">
                <Text style={styles.linkText}>{a('ttFullTable')}</Text>
                <Ionicons name="chevron-forward" size={14} color="#127A50" />
              </PressScale>
            </FadeIn>
          ))}
          {!byStop && !busy ? <EmptyState compact title={a('ttEmptyTitle')} message={a('ttEmptyStop')} /> : null}
        </FadeIn>
      ) : (
        <FadeIn key="route">
          <OutlinedInput value={query} onChangeText={t => { setQuery(t); setRoutes(null); }} placeholder={a('ttSearch')} autoCapitalize="characters" onSubmit={findRoutes} />
          <GradientButton label={a('fsSearch')} icon="search" onPress={findRoutes} disabled={!query.trim()} />
          {routes?.map((r, i) => (
            <FadeIn key={r.id} delay={stagger(i, 30)}>
              <PressScale hoverLift={false} style={styles.row} onPress={() => { setRoute(r.routeNumber); setQuery(r.routeNumber); setRoutes(null); }} accessibilityRole="button">
                <Text style={styles.badge}>{r.routeNumber}</Text>
                <Text style={styles.rowText} numberOfLines={1}>{r.origin && r.destination ? `${r.origin} ⇄ ${r.destination}` : r.routeName}</Text>
              </PressScale>
            </FadeIn>
          ))}
          {routes && !routes.length ? <EmptyState compact title={a('fsNoRouteTitle')} message={a('fsNoRouteMsg')} /> : null}
          {loading ? <View style={{ marginTop: 16, gap: 8 }}><Skeleton height={40} /><Skeleton height={140} /></View> : null}
          {tt && route ? <FadeIn style={styles.card}><Departures tt={tt} /></FadeIn> : null}
          {!route && !routes ? <EmptyState compact title={a('ttEmptyTitle')} message={a('ttEmptyRoute')} /> : null}
        </FadeIn>
      )}
      {(tt && route) || byStop?.length ? (
        <>
          <Text style={styles.note}>{a('ttScheduledNote')}</Text>
          {route ? <GradientButton label={a('ttSeeLive')} icon="radio-outline" onPress={() => router.push({ pathname: '/track-route', params: { route } } as any)} /> : null}
        </>
      ) : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  tabs: { flexDirection: 'row', alignSelf: 'center', borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 6, overflow: 'hidden', marginBottom: 20 },
  tab: { paddingHorizontal: 22, minHeight: 50, justifyContent: 'center', backgroundColor: '#FFFFFF' },
  tabOn: { backgroundColor: '#FDBE2E' },
  tabText: { fontSize: 16, color: '#1E1E24' },
  tabTextOn: { fontWeight: '700' },
  card: { marginTop: 14, borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 14, padding: 14, backgroundColor: '#FFFFFF' },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  cardTitle: { flex: 1, color: '#1E1E24', fontWeight: '600' },
  badge: { backgroundColor: '#12355B', color: '#FFFFFF', fontWeight: '900', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 50, borderBottomWidth: 1, borderBottomColor: '#EEE' },
  rowText: { flex: 1, color: '#1E1E24' },
  dirRow: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  dirBtn: { flex: 1, minHeight: 42, borderRadius: 10, borderWidth: 1.5, borderColor: GREEN, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  dirOn: { backgroundColor: GREEN },
  dirText: { fontWeight: '800', color: '#127A50', fontSize: 13 },
  towards: { fontWeight: '800', color: '#127A50', marginBottom: 4 },
  from: { color: '#666', fontSize: 12, marginBottom: 6 },
  next: { color: '#127A50', fontWeight: '900', fontSize: 15, marginBottom: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  time: { minWidth: 62, paddingVertical: 7, borderRadius: 9, backgroundColor: '#EAF8F1', alignItems: 'center' },
  timePast: { backgroundColor: '#F2F3F5' },
  timeNext: { backgroundColor: GREEN },
  timeText: { fontWeight: '800', color: '#127A50' },
  link: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start', marginTop: 10, minHeight: 36 },
  linkText: { color: '#127A50', fontWeight: '800' },
  note: { color: '#777', fontSize: 12, marginTop: 14, lineHeight: 17 },
  muted: { color: '#777', marginTop: 8 },
});
