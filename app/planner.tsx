import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { useNetworkVehicles } from '../hooks/useNetworkVehicles';
import { useRecentSearches } from '../hooks/useRecentSearches';
import { NetworkApi } from '../services/networkApi';
import { NetworkJourneyPlan } from '../types/network';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OriginDestination, RecentList } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import { LiveBusesMap } from '../components/feature/LiveBusesMap';
import { FadeIn, PressScale, Skeleton, stagger } from '../components/ui/motion';

type Sort = 'FASTEST' | 'FEWEST_CHANGES' | 'FEWEST_STOPS';
const LEG_COLORS = ['#1976D2', '#F28C28', '#7B3FB8'];

/** Journey Planner: origin → destination options on the BMTC network, with every live bus on the map. */
export default function PlannerScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const { data, vehicles } = useNetworkVehicles(undefined, 20000);
  const recent = useRecentSearches<{ key: string; from: string; to: string }>('planner');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [plans, setPlans] = useState<NetworkJourneyPlan[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFilter, setShowFilter] = useState(false);
  const [sort, setSort] = useState<Sort>('FASTEST');
  const [directOnly, setDirectOnly] = useState(false);
  const [picked, setPicked] = useState(0);

  const search = async (f = from, t = to) => {
    if (f.trim().length < 2 || t.trim().length < 2 || busy) return;
    setBusy(true);
    setError(null);
    setPlans(null);
    setPicked(0);
    try {
      const r = await NetworkApi.journey(f.trim(), t.trim());
      setPlans(r.plans);
      recent.add({ key: `${f.trim()}→${t.trim()}`.toLowerCase(), from: f.trim(), to: t.trim() });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const shown = useMemo(() => {
    let list = [...(plans || [])];
    if (directOnly) list = list.filter(p => !p.transferCount);
    const stops = (p: NetworkJourneyPlan) => p.legs.reduce((s, l) => s + (l.stopCount || 0), 0);
    list.sort((x, y) =>
      sort === 'FEWEST_CHANGES' ? (x.transferCount || 0) - (y.transferCount || 0) || x.totalDurationMinutes - y.totalDurationMinutes
        : sort === 'FEWEST_STOPS' ? stops(x) - stops(y)
          : x.totalDurationMinutes - y.totalDurationMinutes);
    return list.slice(0, 6);
  }, [plans, sort, directOnly]);

  const plan = shown[picked];
  const routeLines = useMemo(
    () => (plan?.legs || []).filter((l: any) => (l.geometry?.length || 0) > 1).map((l: any, i: number) => ({ coords: l.geometry as [number, number][], color: LEG_COLORS[i % 3] })),
    [plan]
  );
  const pois = useMemo(() => {
    if (!plan) return [];
    const first = plan.legs[0].fromStop as any;
    const last = plan.legs[plan.legs.length - 1].toStop as any;
    return [
      first?.latitude ? { id: 'from', latitude: first.latitude, longitude: first.longitude, label: first.name, emoji: '🟢', color: '#1FC79A' } : null,
      last?.latitude ? { id: 'to', latitude: last.latitude, longitude: last.longitude, label: last.name, emoji: '🏁', color: '#B1285F' } : null,
    ].filter(Boolean) as any[];
  }, [plan]);

  return (
    <FeatureShell
      title={a('tileJourney')}
      icon="navigate-outline"
      color="#F7B21B"
      renderMap={mapType => <LiveBusesMap vehicles={vehicles} live={!!data?.live_connected} mapType={mapType} routeLines={routeLines} pois={pois} />}
    >
      <OriginDestination from={from} to={to} setFrom={setFrom} setTo={setTo} fromLabel={a('fsEnterOrigin')} toLabel={a('fsEnterDestination')} swapLabel={a('planSwap')} />
      <View style={styles.filterRow}>
        <PressScale hoverLift={false} style={[styles.filterBtn, showFilter && styles.filterOn]} onPress={() => setShowFilter(s => !s)} accessibilityRole="button"
          accessibilityState={{ expanded: showFilter }}>
          <Ionicons name="options-outline" size={20} color="#1E1E24" />
          <Text style={styles.filterText}>{a('fsFilter')}</Text>
        </PressScale>
      </View>
      {showFilter ? (
        <FadeIn from="top" distance={8} duration={240} style={styles.filters}>
          <Text style={styles.filterLabel}>{a('fsSortBy')}</Text>
          <View style={styles.chips}>
            {([['FASTEST', 'fsFastest'], ['FEWEST_CHANGES', 'fsFewestChanges'], ['FEWEST_STOPS', 'fsFewestStops']] as const).map(([k, l]) => (
              <PressScale key={k} hoverLift={false} style={[styles.chip, sort === k && styles.chipOn]} onPress={() => setSort(k)} accessibilityRole="radio" accessibilityState={{ selected: sort === k }}>
                <Text style={[styles.chipText, sort === k && { color: '#FFFFFF' }]}>{a(l)}</Text>
              </PressScale>
            ))}
          </View>
          <PressScale hoverLift={false} style={[styles.chip, { alignSelf: 'flex-start', marginTop: 8 }, directOnly && styles.chipOn]} onPress={() => setDirectOnly(d => !d)}
            accessibilityRole="checkbox" accessibilityState={{ checked: directOnly }}>
            <Text style={[styles.chipText, directOnly && { color: '#FFFFFF' }]}>{directOnly ? '✓ ' : ''}{a('fsDirectOnly')}</Text>
          </PressScale>
        </FadeIn>
      ) : null}
      <GradientButton label={busy ? a('fsSearching') : a('fsSearch')} icon="search" onPress={() => search()} busy={busy} disabled={from.trim().length < 2 || to.trim().length < 2} />

      {busy ? <View style={{ gap: 10, marginTop: 18 }}>{[0, 1, 2].map(i => <Skeleton key={i} height={96} radius={14} />)}</View> : null}
      {error ? <Text style={styles.warn}>{error}</Text> : null}
      {plans && !shown.length ? <EmptyState compact title={a('fsNoJourney')} message={a('planNone')} /> : null}
      {shown.map((p, i) => (
        <FadeIn key={p.id} delay={stagger(i, 70)}>
          <PressScale style={[styles.plan, picked === i && styles.planOn]} hoverLift={false} onPress={() => setPicked(i)} accessibilityRole="radio" accessibilityState={{ selected: picked === i }}>
            <View style={styles.planTop}>
              {p.legs.map((l, li) => (
                <React.Fragment key={li}>
                  {li > 0 ? <Ionicons name="arrow-forward" size={14} color="#888" /> : null}
                  <Text style={[styles.badge, { backgroundColor: LEG_COLORS[li % 3] }]}>{l.routeNumber}</Text>
                </React.Fragment>
              ))}
              <Text style={styles.mins}>{p.totalDurationMinutes} min</Text>
            </View>
            <Text style={styles.trip} numberOfLines={2}>{p.legs[0].fromStop.name} → {p.legs[p.legs.length - 1].toStop.name}</Text>
            <Text style={styles.meta}>
              {a('planStops', { n: p.legs.reduce((s, l) => s + (l.stopCount || 0), 0) })}
              {p.transferCount ? ` · ${a('planChange')}` : ` · ${a('fsDirect')}`}
              {(p as any).legs[0].activeBusesCount ? ` · ${a('fsLiveOnRoute', { n: (p as any).legs[0].activeBusesCount })}` : ''}
            </Text>
            {picked === i ? (
              <View style={styles.planActions}>
                <PressScale hoverLift={false} style={styles.action} onPress={() => router.push({ pathname: '/access/buy', params: { route: p.legs[0].routeNumber } } as any)} accessibilityRole="button">
                  <Ionicons name="ticket-outline" size={16} color="#B1285F" /><Text style={styles.actionText}>{a('planBuy')}</Text>
                </PressScale>
                <PressScale hoverLift={false} style={styles.action} onPress={() => router.push({ pathname: '/fare', params: { from: p.legs[0].fromStop.name, to: p.legs[p.legs.length - 1].toStop.name } } as any)} accessibilityRole="button">
                  <Ionicons name="calculator-outline" size={16} color="#B1285F" /><Text style={styles.actionText}>{a('tileFare')}</Text>
                </PressScale>
              </View>
            ) : null}
          </PressScale>
        </FadeIn>
      ))}
      {shown.length ? <Text style={styles.note}>{a('planScheduled')}</Text> : null}

      {!plans && !busy ? (
        <RecentList title={a('fsRecent')} items={recent.items.map(r => ({ key: r.key, label: `${r.from} → ${r.to}` }))} icon="git-merge-outline"
          onClear={recent.clear} clearLabel={a('fsClear')}
          onPick={k => { const r = recent.items.find(x => x.key === k); if (r) { setFrom(r.from); setTo(r.to); search(r.from, r.to); } }} />
      ) : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  filterRow: { flexDirection: 'row', justifyContent: 'flex-end', marginTop: 16, marginBottom: 6 },
  filterBtn: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, paddingHorizontal: 18, borderRadius: 22, borderWidth: 1, borderColor: '#D9DBE0', backgroundColor: '#FFFFFF' },
  filterOn: { borderColor: '#B1285F' },
  filterText: { fontSize: 15, fontWeight: '600', color: '#1E1E24' },
  filters: { backgroundColor: '#FBF4F7', borderRadius: 12, padding: 12, marginBottom: 10 },
  filterLabel: { fontSize: 12, fontWeight: '800', color: '#55565C', marginBottom: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { minHeight: 36, paddingHorizontal: 12, borderRadius: 18, borderWidth: 1.5, borderColor: '#B1285F', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  chipOn: { backgroundColor: '#B1285F' },
  chipText: { color: '#B1285F', fontWeight: '700', fontSize: 13 },
  plan: { borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 14, padding: 14, marginTop: 12, backgroundColor: '#FFFFFF' },
  planOn: { borderColor: '#B1285F', borderWidth: 2, backgroundColor: '#FFF7FA' },
  planTop: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  badge: { color: '#FFFFFF', fontWeight: '900', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, overflow: 'hidden', fontSize: 13 },
  mins: { marginLeft: 'auto', fontWeight: '900', color: '#1E1E24' },
  trip: { marginTop: 8, color: '#1E1E24' },
  meta: { marginTop: 4, color: '#666', fontSize: 12 },
  planActions: { flexDirection: 'row', gap: 8, marginTop: 10 },
  action: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 12, borderRadius: 10, borderWidth: 1.5, borderColor: '#B1285F' },
  actionText: { color: '#B1285F', fontWeight: '800' },
  note: { color: '#777', fontSize: 12, marginTop: 12 },
  warn: { color: '#8E1C1C', marginTop: 12 },
});
