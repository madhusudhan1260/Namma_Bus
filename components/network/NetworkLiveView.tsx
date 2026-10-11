import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useTransit } from '../../context/TransitContext';
import { useNetworkVehicles } from '../../hooks/useNetworkVehicles';
import { NetworkApi } from '../../services/networkApi';
import { NetworkRouteSummary, NetworkStop, NetworkVehicle } from '../../types/network';
import { CITY_CENTRE, Coords, positionIfGranted, requestPosition } from '../access/location';
import { FadeIn, PressScale, Pulse, Skeleton, SlideUp, stagger } from '../ui/motion';
import NetworkMap from './NetworkMap';
import { NetworkBusSheet } from './NetworkBusSheet';

type Stand = NetworkStop & { distanceMeters?: number; walkingMinutes?: number; routes?: string[] };
type Mode = { kind: 'stands' } | { kind: 'route'; route: string } | { kind: 'bus'; vehicleId: string };
type Origin = { coords: Coords; source: 'gps' | 'centre' | 'stop'; label?: string };

const REG = /^KA\s?\d{1,2}/i;

/**
 * The ನಮ್ಮ Bus map.
 *  • Opens on NEARBY BUS STANDS (no buses): stands around you (or the city centre, labelled) as bus-stop pins,
 *    with distance, walking time and the routes that stop there.
 *  • Buses appear ONLY after a search: pick a route (or tap a route on a stand) to see that route's live buses
 *    and line; type a registration (KA…) to find one bus. Everything comes from the real BMTC network/feed.
 */
export function NetworkLiveView({ initialVehicleId, initialRoute, searchFocus }: {
  initialVehicleId?: string | null;
  initialRoute?: string | null;
  /** Opened from "Track a Bus" / "Track a Live Route": focus the search box with a matching hint */
  searchFocus?: 'bus' | 'route' | null;
} = {}) {
  const { preferredLanguage: lang } = useTransit();
  const { a } = useAccessT();
  const { width } = useWindowDimensions();
  const wide = width >= 900;

  const [mode, setMode] = useState<Mode>(
    initialVehicleId ? { kind: 'bus', vehicleId: initialVehicleId } : initialRoute ? { kind: 'route', route: initialRoute } : { kind: 'stands' }
  );
  useEffect(() => {
    if (initialVehicleId) setMode({ kind: 'bus', vehicleId: initialVehicleId });
    else if (initialRoute) setMode({ kind: 'route', route: initialRoute });
  }, [initialVehicleId, initialRoute]);

  // ---------------- nearby stands ----------------
  const [origin, setOrigin] = useState<Origin | null>(null);
  const [stands, setStands] = useState<Stand[] | null>(null);
  const [standsError, setStandsError] = useState<string | null>(null);
  const [selectedStop, setSelectedStop] = useState<Stand | null>(null);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    let alive = true;
    positionIfGranted().then(p => {
      if (alive) setOrigin(p ? { coords: p, source: 'gps' } : { coords: CITY_CENTRE, source: 'centre' });
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!origin) return;
    setStands(null);
    setStandsError(null);
    NetworkApi.stopsNearby(origin.coords.latitude, origin.coords.longitude, 1200, 20)
      .then(r => setStands(r.stops as Stand[]))
      .catch(e => setStandsError(e.message || a('mapNoStands')));
  }, [origin?.coords.latitude, origin?.coords.longitude]); // eslint-disable-line react-hooks/exhaustive-deps

  const useMyLocation = async () => {
    setLocating(true);
    const p = await requestPosition();
    setLocating(false);
    if (p) {
      setSelectedStop(null);
      setOrigin({ coords: p, source: 'gps' });
      setMode({ kind: 'stands' });
    } else setStandsError(a('mapLocationDenied'));
  };

  // ---------------- buses (only in route / bus mode) ----------------
  const routeKey = mode.kind === 'route' ? mode.route : undefined;
  const { data, vehicles, loading: busesLoading } = useNetworkVehicles(routeKey, 15000, mode.kind !== 'stands');
  const [routeLines, setRouteLines] = useState<{ coords: [number, number][]; color?: string }[]>([]);
  const [selectedBusId, setSelectedBusId] = useState<string | null>(initialVehicleId || null);

  useEffect(() => {
    setRouteLines([]);
    if (mode.kind !== 'route') return;
    NetworkApi.route(mode.route)
      .then(r => setRouteLines((r.directions || []).filter(d => (d.geometry?.length || 0) > 1).map((d, i) => ({ coords: d.geometry!, color: i ? '#F28C28' : '#1976D2' }))))
      .catch(() => setRouteLines([]));
  }, [mode]);

  const shownBuses: NetworkVehicle[] = useMemo(() => {
    if (mode.kind === 'route') return vehicles;
    if (mode.kind === 'bus') return vehicles.filter(v => v.vehicle_id === mode.vehicleId);
    return [];
  }, [mode, vehicles]);
  const selectedBus = useMemo(() => shownBuses.find(v => v.vehicle_id === selectedBusId) || null, [shownBuses, selectedBusId]);

  // ---------------- search ----------------
  const [query, setQuery] = useState('');
  const searchRef = React.useRef<TextInput>(null);
  useEffect(() => {
    if (searchFocus) setTimeout(() => searchRef.current?.focus(), 350);
  }, [searchFocus]);
  const [results, setResults] = useState<{ routes: NetworkRouteSummary[]; stops: NetworkStop[]; buses: NetworkVehicle[] } | null>(null);
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    setSearching(true);
    const h = setTimeout(async () => {
      try {
        const [net, all] = await Promise.all([
          NetworkApi.search(q),
          REG.test(q) ? NetworkApi.vehicles().catch(() => null) : Promise.resolve(null),
        ]);
        const needle = q.replace(/\s/g, '').toUpperCase();
        const buses = (all?.vehicles || []).filter(v => (v.vehicle_number || '').replace(/\s/g, '').toUpperCase().includes(needle)).slice(0, 8);
        setResults({ routes: net.routes.slice(0, 8), stops: net.stops.slice(0, 6), buses });
      } catch {
        setResults({ routes: [], stops: [], buses: [] });
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(h);
  }, [query]);

  const showRoute = (route: string) => {
    setQuery('');
    setSelectedBusId(null);
    setMode({ kind: 'route', route });
  };
  const showStop = (s: NetworkStop) => {
    setQuery('');
    setMode({ kind: 'stands' });
    setSelectedStop(null);
    setOrigin({ coords: { latitude: s.latitude, longitude: s.longitude }, source: 'stop', label: s.name });
  };
  const backToStands = () => {
    setMode({ kind: 'stands' });
    setSelectedBusId(null);
  };

  const originLabel =
    origin?.source === 'gps' ? a('mapNearYou') : origin?.source === 'stop' ? a('mapNearStop', { stop: origin.label || '' }) : a('mapNearCentre');

  // ---------------- pieces ----------------
  const searchBar = (
    <View style={styles.searchBox}>
      <Ionicons name="search" size={18} color={COLORS.textMuted} style={{ marginRight: 8 }} />
      <TextInput
        ref={searchRef}
        value={query}
        onChangeText={setQuery}
        placeholder={searchFocus === 'bus' ? a('mapSearchBus') : searchFocus === 'route' ? a('mapSearchRoute') : a('mapSearchPlaceholder')}
        placeholderTextColor={COLORS.textMuted}
        style={styles.searchInput}
        autoCorrect={false}
        accessibilityLabel={a('mapSearchPlaceholder')}
      />
      {searching ? <ActivityIndicator size="small" color={COLORS.primary} /> : null}
      {query ? (
        <TouchableOpacity onPress={() => setQuery('')} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel={a('cancel')}>
          <Ionicons name="close-circle" size={18} color={COLORS.textMuted} />
        </TouchableOpacity>
      ) : null}
    </View>
  );

  const resultsPanel = results ? (
    <FadeIn from="top" distance={8} duration={260} style={styles.results}>
      <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 320 }}>
        {!results.routes.length && !results.stops.length && !results.buses.length ? <Text style={styles.muted}>{a('mapNoResults')}</Text> : null}
        {results.buses.map((v, i) => (
          <FadeIn key={`b${v.vehicle_id}`} delay={stagger(i, 30)}>
            <PressScale style={styles.resultRow} onPress={() => { setQuery(''); setSelectedBusId(v.vehicle_id); setMode({ kind: 'bus', vehicleId: v.vehicle_id }); }}
              accessibilityRole="button" accessibilityLabel={`${a('mapBus')} ${v.vehicle_number}`}>
              <Ionicons name="bus" size={18} color={COLORS.success} style={{ marginRight: 10 }} />
              <Text style={styles.resultText} numberOfLines={1}>{v.vehicle_number} · {a('route')} {v.route_number || '—'}</Text>
            </PressScale>
          </FadeIn>
        ))}
        {results.routes.map((r, i) => (
          <FadeIn key={`r${r.id}`} delay={stagger(i, 30)}>
            <PressScale style={styles.resultRow} onPress={() => showRoute(r.routeNumber)} accessibilityRole="button"
              accessibilityLabel={`${a('route')} ${r.routeNumber}. ${a('mapShowBuses')}`}>
              <View style={styles.routeBadge}><Text style={styles.routeBadgeText} numberOfLines={1}>{r.routeNumber}</Text></View>
              <Text style={styles.resultText} numberOfLines={2}>{r.origin && r.destination ? `${r.origin} ⇄ ${r.destination}` : r.routeName}</Text>
              <Text style={styles.resultAction}>{a('mapShowBuses')}</Text>
            </PressScale>
          </FadeIn>
        ))}
        {results.stops.map((s, i) => (
          <FadeIn key={`s${s.id}`} delay={stagger(i + results.routes.length, 30)}>
            <PressScale style={styles.resultRow} onPress={() => showStop(s)} accessibilityRole="button" accessibilityLabel={`${a('mapStop')} ${s.name}`}>
              <Text style={{ fontSize: 16, marginRight: 10 }}>🚏</Text>
              <Text style={styles.resultText} numberOfLines={1}>{s.name}{s.nameKannada ? `  ·  ${s.nameKannada}` : ''}</Text>
            </PressScale>
          </FadeIn>
        ))}
      </ScrollView>
    </FadeIn>
  ) : null;

  const busBanner =
    mode.kind !== 'stands' ? (
      <FadeIn from="top" distance={10} duration={300} style={styles.banner}>
        <Pulse style={{ width: 12, height: 12, marginRight: 10 }}>
          <View style={[styles.liveDot, { backgroundColor: shownBuses.length ? COLORS.success : COLORS.textMuted }]} />
        </Pulse>
        <View style={{ flex: 1 }}>
          <Text style={styles.bannerTitle} numberOfLines={1}>
            {busesLoading
              ? a('mapLoadingBuses')
              : mode.kind === 'route'
                ? shownBuses.length ? a('mapShowingRoute', { n: shownBuses.length, route: mode.route }) : a('mapNoBusesRoute', { route: mode.route })
                : shownBuses.length ? a('mapShowingBus', { bus: shownBuses[0].vehicle_number || '' }) : a('mapBusNotInFeed')}
          </Text>
          <Text style={styles.bannerSub} numberOfLines={1}>{data?.live_connected === false ? a('mapFeedUnavailable') : a('mapFeedSource')}</Text>
        </View>
        <PressScale style={styles.bannerClose} onPress={backToStands} accessibilityRole="button" accessibilityLabel={a('mapBackToStands')}>
          <Ionicons name="close" size={18} color={COLORS.deepNavy} />
          <Text style={styles.bannerCloseText}>{a('mapStops')}</Text>
        </PressScale>
      </FadeIn>
    ) : null;

  const standCard = (s: Stand, i: number) => {
    const active = selectedStop?.id === s.id;
    const routes = s.routes || [];
    return (
      <FadeIn key={s.id} delay={stagger(i)} style={[styles.stand, active && styles.standActive]}>
        {/* Only the header is the expand button; the route chips are separate buttons (never nested) */}
        <PressScale
          hoverLift={false}
          onPress={() => setSelectedStop(active ? null : s)}
          accessibilityRole="button"
          accessibilityState={{ expanded: active }}
          accessibilityLabel={`${s.name}, ${s.distanceMeters ?? ''} m, ${routes.length} ${a('mapRoutesHere')}`}
        >
          <View style={styles.standTop}>
            <View style={[styles.standIcon, active && { backgroundColor: '#F28C28' }]}><Text style={{ fontSize: 16 }}>🚏</Text></View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.standName} numberOfLines={1}>{s.name}</Text>
              {s.nameKannada ? <Text style={styles.standKn} numberOfLines={1}>{s.nameKannada}</Text> : null}
            </View>
            <View style={{ alignItems: 'flex-end' }}>
              {s.distanceMeters != null ? <Text style={styles.distance}>{s.distanceMeters < 1000 ? `${s.distanceMeters} m` : `${(s.distanceMeters / 1000).toFixed(1)} km`}</Text> : null}
              {s.walkingMinutes != null ? <Text style={styles.walk}>🚶 {a('mapWalk', { m: s.walkingMinutes })}</Text> : null}
            </View>
          </View>
        </PressScale>
          {routes.length ? (
            <View style={styles.chips}>
              {(active ? routes : routes.slice(0, 6)).map(r => (
                <PressScale key={r} style={styles.chip} hoverLift={false} onPress={() => showRoute(r)} accessibilityRole="button"
                  accessibilityLabel={`${a('route')} ${r}. ${a('mapShowBuses')}`}>
                  <Text style={styles.chipText}>{r}</Text>
                </PressScale>
              ))}
              {!active && routes.length > 6 ? <Text style={styles.more}>{a('mapMoreRoutes', { n: routes.length - 6 })}</Text> : null}
            </View>
          ) : null}
          {active ? <Text style={styles.hint}>{a('mapTapRouteHint')}</Text> : null}
        
      </FadeIn>
    );
  };

  const standsPanel = (
    <SlideUp visible={mode.kind === 'stands'} style={wide ? styles.sidePanel : styles.sheet}>
      <View style={styles.sheetHead}>
        <View style={{ flex: 1 }}>
          <Text style={styles.sheetTitle} accessibilityRole="header">{a('mapNearbyStands')}</Text>
          <Text style={styles.sheetSub} numberOfLines={1}>{originLabel}</Text>
        </View>
        {origin?.source !== 'gps' ? (
          <PressScale style={styles.locBtn} onPress={useMyLocation} accessibilityRole="button" accessibilityLabel={a('mapUseLocation')}>
            {locating ? <ActivityIndicator size="small" color="#FFFFFF" /> : <Ionicons name="locate" size={16} color="#FFFFFF" />}
            <Text style={styles.locText}>{a('mapUseLocation')}</Text>
          </PressScale>
        ) : null}
      </View>
      {standsError ? <Text style={styles.warn}>{standsError}</Text> : null}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: SPACING.md }} keyboardShouldPersistTaps="handled">
        {!stands && !standsError
          ? [0, 1, 2].map(i => (
              <View key={i} style={styles.stand}>
                <Skeleton width="60%" height={14} />
                <Skeleton width="35%" height={10} style={{ marginTop: 8 }} />
                <Skeleton width="80%" height={22} style={{ marginTop: 10 }} />
              </View>
            ))
          : null}
        {stands && !stands.length ? <Text style={styles.muted}>{a('mapNoStands')}</Text> : null}
        {(stands || []).map(standCard)}
      </ScrollView>
    </SlideUp>
  );

  return (
    <View style={styles.container}>
      {searchBar}
      {resultsPanel}
      {busBanner}
      <View style={[styles.body, wide && styles.bodyWide]}>
        {wide ? standsPanel : null}
        <View style={styles.mapWrap}>
          <NetworkMap
            vehicles={shownBuses}
            selectedVehicleId={selectedBusId}
            onSelectVehicle={setSelectedBusId}
            routeLines={mode.kind === 'route' ? routeLines : []}
            stops={mode.kind === 'stands' ? stands || [] : []}
            stopVariant="stand"
            selectedStopId={selectedStop?.id || null}
            onSelectStop={s => setSelectedStop((stands || []).find(x => x.id === s.id) || (s as Stand))}
            userLocation={origin?.source === 'gps' ? origin.coords : null}
            focus={
              selectedStop ? { latitude: selectedStop.latitude, longitude: selectedStop.longitude }
                : selectedBus ? { latitude: selectedBus.latitude, longitude: selectedBus.longitude } : null
            }
          />
        </View>
        {!wide && mode.kind === 'stands' ? standsPanel : null}
      </View>
      <NetworkBusSheet vehicle={selectedBus} missing={!!selectedBusId && !selectedBus && !busesLoading && mode.kind !== 'stands'} lang={lang}
        onClose={() => setSelectedBusId(null)} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  body: { flex: 1 },
  bodyWide: { flexDirection: 'row' },
  searchBox: {
    flexDirection: 'row', alignItems: 'center', minHeight: 48, marginHorizontal: SPACING.md, marginTop: SPACING.sm, marginBottom: SPACING.sm,
    paddingHorizontal: SPACING.md, borderRadius: 14, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
    shadowColor: '#0B2545', shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 2 },
  },
  searchInput: { flex: 1, fontSize: 15, color: COLORS.textPrimary, minHeight: 44 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  results: {
    marginHorizontal: SPACING.md, backgroundColor: COLORS.surface, borderRadius: 14, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.sm,
    marginBottom: SPACING.sm, shadowColor: '#0B2545', shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, zIndex: 5,
  },
  resultRow: { flexDirection: 'row', alignItems: 'center', minHeight: 50, paddingHorizontal: 6, borderRadius: 10 },
  routeBadge: { backgroundColor: COLORS.deepNavy, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, marginRight: 10, maxWidth: 110 },
  routeBadgeText: { color: '#FFFFFF', fontWeight: '800', fontSize: 12 },
  resultText: { flex: 1, fontSize: 13, color: COLORS.textPrimary },
  resultAction: { fontSize: 11, fontWeight: '800', color: COLORS.primaryDark, marginLeft: 6 },
  banner: {
    flexDirection: 'row', alignItems: 'center', marginHorizontal: SPACING.md, marginBottom: SPACING.sm, padding: 10, borderRadius: 14,
    backgroundColor: '#EAF3EC', borderWidth: 1, borderColor: '#CDE6D3',
  },
  liveDot: { width: 10, height: 10, borderRadius: 5 },
  bannerTitle: { fontWeight: '800', color: COLORS.textPrimary, fontSize: 13 },
  bannerSub: { color: COLORS.textSecondary, fontSize: 11, marginTop: 1 },
  bannerClose: { flexDirection: 'row', alignItems: 'center', minHeight: 40, paddingHorizontal: 10, borderRadius: 20, backgroundColor: '#FFFFFF' },
  bannerCloseText: { marginLeft: 4, fontWeight: '800', color: COLORS.deepNavy, fontSize: 12 },
  mapWrap: { flex: 1, minHeight: 260, overflow: 'hidden' },
  sheet: {
    maxHeight: '46%', backgroundColor: COLORS.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: SPACING.md, paddingTop: SPACING.md,
    shadowColor: '#0B2545', shadowOpacity: 0.12, shadowRadius: 16, shadowOffset: { width: 0, height: -4 }, elevation: 8,
  },
  sidePanel: { width: 380, backgroundColor: COLORS.surface, padding: SPACING.md, borderRightWidth: 1, borderRightColor: COLORS.border },
  sheetHead: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACING.sm },
  sheetTitle: { fontSize: 17, fontWeight: '900', color: COLORS.deepNavy },
  sheetSub: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  locBtn: { flexDirection: 'row', alignItems: 'center', minHeight: 40, paddingHorizontal: 12, borderRadius: 20, backgroundColor: COLORS.deepNavy },
  locText: { color: '#FFFFFF', fontWeight: '800', fontSize: 12, marginLeft: 6 },
  stand: { borderWidth: 1, borderColor: '#E3E9F0', borderRadius: 16, padding: 12, marginBottom: 10, backgroundColor: '#FFFFFF' },
  standActive: { borderColor: '#F28C28', backgroundColor: '#FFF8F0' },
  standTop: { flexDirection: 'row', alignItems: 'center' },
  standIcon: { width: 36, height: 36, borderRadius: 10, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  standName: { fontWeight: '800', color: COLORS.textPrimary, fontSize: 14 },
  standKn: { color: COLORS.textSecondary, fontSize: 12, marginTop: 1 },
  distance: { fontWeight: '900', color: COLORS.deepNavy, fontSize: 13 },
  walk: { color: COLORS.textSecondary, fontSize: 11, marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  chip: { minHeight: 32, paddingHorizontal: 10, justifyContent: 'center', borderRadius: 8, backgroundColor: COLORS.deepNavy },
  chipText: { color: '#FFFFFF', fontWeight: '800', fontSize: 12 },
  more: { alignSelf: 'center', color: COLORS.textSecondary, fontSize: 12, fontWeight: '700' },
  hint: { color: COLORS.textSecondary, fontSize: 11, marginTop: 8 },
  muted: { color: COLORS.textSecondary, fontSize: 13, padding: SPACING.sm },
  warn: { color: '#7A4B00', fontSize: 12, fontWeight: '700', marginBottom: SPACING.sm },
});
