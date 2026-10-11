import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { useNetworkVehicles } from '../hooks/useNetworkVehicles';
import { useRecentSearches } from '../hooks/useRecentSearches';
import { NetworkApi } from '../services/networkApi';
import { NetworkRouteSummary } from '../types/network';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OutlinedInput, RecentList } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import { LiveBusesMap } from '../components/feature/LiveBusesMap';
import { FadeIn, PressScale, stagger } from '../components/ui/motion';

/** Track a Live Route: every live bus on the map; pick a route to see its line and only its live buses. */
export default function TrackRouteScreen() {
  const { a } = useAccessT();
  const params = useLocalSearchParams<{ route?: string }>();
  const [route, setRoute] = useState<string | null>(typeof params.route === 'string' && params.route ? params.route : null);
  const all = useNetworkVehicles(undefined, 20000, !route);
  const one = useNetworkVehicles(route || undefined, 15000, !!route);
  const recent = useRecentSearches<{ key: string; label: string }>('track-route');
  const [query, setQuery] = useState(route || '');
  const [results, setResults] = useState<NetworkRouteSummary[] | null>(null);
  const [lines, setLines] = useState<{ coords: [number, number][]; color?: string }[]>([]);
  const [detail, setDetail] = useState<{ origin?: string | null; destination?: string | null } | null>(null);
  const [searching, setSearching] = useState(false);

  const find = async (q = query) => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      setResults((await NetworkApi.searchRoutes(q.trim(), 12)).routes);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };
  const choose = (r: string) => {
    setRoute(r);
    setQuery(r);
    setResults(null);
    recent.add({ key: r, label: r });
  };

  useEffect(() => {
    setLines([]);
    setDetail(null);
    if (!route) return;
    NetworkApi.route(route)
      .then(d => {
        setDetail({ origin: d.origin, destination: d.destination });
        setLines((d.directions || []).filter(x => (x.geometry?.length || 0) > 1).map((x, i) => ({ coords: x.geometry!, color: i ? '#F28C28' : '#1976D2' })));
      })
      .catch(() => undefined);
  }, [route]);

  const src = route ? one : all;
  const buses = useMemo(() => [...src.vehicles].sort((x, y) => (x.freshness_seconds || 0) - (y.freshness_seconds || 0)), [src.vehicles]);

  return (
    <FeatureShell
      title={a('tileTrackRoute')}
      icon="git-network-outline"
      color="#2E8BF0"
      renderMap={mapType => <LiveBusesMap vehicles={src.vehicles} live={!!src.data?.live_connected} mapType={mapType} routeLines={lines} />}
    >
      <Text style={styles.label}>{a('fsSearchRouteNumber')}</Text>
      <OutlinedInput value={query} onChangeText={t => { setQuery(t); if (route) setRoute(null); }} placeholder="Eg: 500-D" autoCapitalize="characters" autoFocus={!route}
        onSubmit={() => find()} />
      <GradientButton label={searching ? a('fsSearching') : a('fsSearch')} icon="search" onPress={() => find()} busy={searching} disabled={!query.trim()} />

      {results?.map((r, i) => (
        <FadeIn key={r.id} delay={stagger(i, 40)}>
          <PressScale hoverLift={false} style={styles.row} onPress={() => choose(r.routeNumber)} accessibilityRole="button">
            <Text style={styles.badge}>{r.routeNumber}</Text>
            <Text style={styles.rowText} numberOfLines={2}>{r.origin && r.destination ? `${r.origin} ⇄ ${r.destination}` : r.routeName}</Text>
            <Ionicons name="chevron-forward" size={16} color="#AAA" />
          </PressScale>
        </FadeIn>
      ))}
      {results && !results.length ? <EmptyState compact title={a('fsNoRouteTitle')} message={a('fsNoRouteMsg')} /> : null}

      {route ? (
        <FadeIn style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={[styles.badge, { fontSize: 16 }]}>{route}</Text>
            <Text style={styles.cardTitle} numberOfLines={2}>{detail?.origin && detail?.destination ? `${detail.origin} ⇄ ${detail.destination}` : ''}</Text>
          </View>
          <Text style={styles.count}>
            {one.loading ? a('mapLoadingBuses') : buses.length ? a('mapShowingRoute', { n: buses.length, route }) : a('mapNoBusesRoute', { route })}
          </Text>
          {buses.slice(0, 10).map((v, i) => (
            <FadeIn key={v.vehicle_id} delay={stagger(i, 40)} style={styles.busRow}>
              <Ionicons name="bus" size={18} color={v.freshness === 'LIVE' ? '#168A45' : '#C47A00'} />
              <Text style={styles.busText} numberOfLines={2}>
                {v.vehicle_number || v.vehicle_id}
                {v.next_stop?.stop_name ? ` → ${v.next_stop.stop_name}` : ''}
                {v.freshness_seconds != null ? ` · ${a('secondsAgo', { s: v.freshness_seconds })}` : ''}
              </Text>
            </FadeIn>
          ))}
        </FadeIn>
      ) : null}

      {!route && !results ? (
        <RecentList title={a('fsRecent')} items={recent.items} icon="trail-sign-outline" onClear={recent.clear} clearLabel={a('fsClear')} onPick={choose} />
      ) : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 16, fontWeight: '700', color: '#55565C', marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 54, borderBottomWidth: 1, borderBottomColor: '#EEE', paddingHorizontal: 4 },
  badge: { backgroundColor: '#12355B', color: '#FFFFFF', fontWeight: '900', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, overflow: 'hidden' },
  rowText: { flex: 1, color: '#1E1E24' },
  card: { marginTop: 18, borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 14, padding: 14, backgroundColor: '#FFFFFF' },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  cardTitle: { flex: 1, color: '#1E1E24', fontWeight: '700' },
  count: { marginTop: 10, color: '#168A45', fontWeight: '800' },
  busRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8 },
  busText: { flex: 1, color: '#444', fontSize: 13 },
});
