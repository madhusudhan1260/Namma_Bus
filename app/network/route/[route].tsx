import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../../constants/theme';
import { t } from '../../../constants/i18n';
import { useTransit } from '../../../context/TransitContext';
import { useNetworkVehicles } from '../../../hooks/useNetworkVehicles';
import { NetworkApi } from '../../../services/networkApi';
import { NetworkRouteDetail, NetworkStop } from '../../../types/network';
import NetworkMap from '../../../components/network/NetworkMap';
import { NetworkBusSheet } from '../../../components/network/NetworkBusSheet';
import { freshnessColor } from '../../../components/network/networkMapShared';

/** Route details from the imported BMTC network: directions, geometry, ordered stops and live buses. */
export default function NetworkRouteScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ route: string; vehicle?: string }>();
  const routeKey = String(params.route || '');
  const { preferredLanguage: lang } = useTransit();
  const [route, setRoute] = useState<NetworkRouteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState(0);
  const [stops, setStops] = useState<NetworkStop[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(params.vehicle ? String(params.vehicle) : null);
  const { vehicles, loading: busesLoading, data } = useNetworkVehicles(routeKey, 20000);

  useEffect(() => {
    setRoute(null);
    setError(null);
    NetworkApi.route(routeKey).then(setRoute).catch(e => setError(e.message));
  }, [routeKey]);

  useEffect(() => {
    NetworkApi.routeStops(routeKey, direction).then(setStops).catch(() => setStops([]));
  }, [routeKey, direction]);

  // If a bus was passed in, open its direction
  const selected = useMemo(() => vehicles.find(v => v.vehicle_id === selectedId) || null, [vehicles, selectedId]);
  useEffect(() => {
    if (selected?.direction != null) setDirection(selected.direction);
  }, [selected?.vehicle_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirInfo = route?.directions?.find(d => d.direction === direction);
  const lines = useMemo(
    () => (dirInfo?.geometry && dirInfo.geometry.length > 1 ? [{ coords: dirInfo.geometry, color: '#1976D2' }] : []),
    [dirInfo]
  );
  const busesThisDirection = vehicles.filter(v => v.direction == null || v.direction === direction);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/map' as any))} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel={t('authBack', lang)}>
          <Ionicons name="chevron-back" size={24} color={COLORS.deepNavy} />
        </TouchableOpacity>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{routeKey}</Text>
        </View>
        <Text style={styles.title} numberOfLines={2} accessibilityRole="header">
          {route ? `${route.origin || ''} ⇄ ${route.destination || ''}` : ''}
        </Text>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {!route && !error ? <ActivityIndicator style={{ marginTop: SPACING.xl }} color={COLORS.primary} /> : null}

      {route ? (
        <>
          <View style={styles.dirRow}>
            {(route.directions || []).map(d => (
              <TouchableOpacity
                key={d.direction}
                style={[styles.dirBtn, d.direction === direction && styles.dirBtnActive]}
                onPress={() => setDirection(d.direction)}
                accessibilityRole="tab"
                accessibilityState={{ selected: d.direction === direction }}
                accessibilityLabel={`${t('rtTowards', lang)} ${d.destinationName || ''}`}
              >
                <Text style={[styles.dirText, d.direction === direction && styles.dirTextActive]} numberOfLines={1}>
                  {t('rtTowards', lang)} {d.destinationName || ''} ({d.stopCount ?? '—'})
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={styles.mapWrap}>
            <NetworkMap vehicles={busesThisDirection} selectedVehicleId={selectedId} onSelectVehicle={setSelectedId} routeLines={lines} stops={stops} />
          </View>

          <NetworkBusSheet vehicle={selected} missing={!!selectedId && !selected && !busesLoading} lang={lang} onClose={() => setSelectedId(null)} />

          <FlatList
            style={styles.list}
            data={stops}
            keyExtractor={(s, i) => `${s.id}-${i}`}
            ListHeaderComponent={
              <View>
                <Text style={styles.section}>{t('netLiveBuses', lang)}</Text>
                {busesLoading ? <ActivityIndicator color={COLORS.primary} /> : null}
                {!busesLoading && vehicles.length === 0 ? (
                  <Text style={styles.muted}>
                    {t('netNoLiveBuses', lang)} {data?.operational_statement ? `\n${data.operational_statement}` : ''}
                  </Text>
                ) : null}
                {vehicles.map(v => (
                  <TouchableOpacity key={v.vehicle_id} style={styles.busRow} onPress={() => setSelectedId(v.vehicle_id)} accessibilityRole="button" accessibilityLabel={`${t('netBus', lang)} ${v.vehicle_number || v.vehicle_id}`}>
                    <View style={[styles.dot, { backgroundColor: freshnessColor(v.freshness) }]} />
                    <Text style={styles.busText}>
                      {v.vehicle_number || v.vehicle_id} · {t('rtTowards', lang)} {v.destination || t('rtUnknown', lang)} · {v.freshness === 'LIVE' ? t('freshnessLive', lang) : v.freshness === 'RECENT' ? t('freshnessRecent', lang) : t('freshnessStale', lang)}
                    </Text>
                  </TouchableOpacity>
                ))}
                <TouchableOpacity
                  style={styles.buyBtn}
                  onPress={() => router.push({ pathname: '/access/buy', params: { route: routeKey, direction: String(direction), ...(selected ? { vehicle: selected.vehicle_number || selected.vehicle_id } : {}) } } as any)}
                  accessibilityRole="button"
                  accessibilityLabel={t('netBuyTicket', lang)}
                >
                  <Ionicons name="card-outline" size={18} color={COLORS.textInverse} style={{ marginRight: 6 }} />
                  <Text style={styles.buyText}>{t('netBuyTicket', lang)}</Text>
                </TouchableOpacity>
                <Text style={styles.section}>{t('netOrderedStops', lang)} ({stops.length})</Text>
              </View>
            }
            renderItem={({ item, index }) => (
              <View style={styles.stopRow} accessible accessibilityLabel={`${index + 1}. ${item.name}`}>
                <Text style={styles.seq}>{index + 1}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.stopName}>{item.name}</Text>
                  {item.nameKannada ? <Text style={styles.stopKn}>{item.nameKannada}</Text> : null}
                </View>
              </View>
            )}
          />
        </>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm, gap: SPACING.sm },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  badge: { backgroundColor: COLORS.deepNavy, borderRadius: RADIUS.md, paddingHorizontal: 10, paddingVertical: 6 },
  badgeText: { color: COLORS.textInverse, fontWeight: '900' },
  title: { flex: 1, fontSize: 15, fontWeight: '800', color: COLORS.textPrimary },
  error: { color: COLORS.error, padding: SPACING.md },
  dirRow: { flexDirection: 'row', gap: SPACING.sm, paddingHorizontal: SPACING.md, marginBottom: SPACING.sm },
  dirBtn: { flex: 1, minHeight: 44, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface, justifyContent: 'center', paddingHorizontal: 8 },
  dirBtnActive: { backgroundColor: COLORS.deepNavy, borderColor: COLORS.deepNavy },
  dirText: { fontSize: 12, fontWeight: '700', color: COLORS.textPrimary, textAlign: 'center' },
  dirTextActive: { color: COLORS.textInverse },
  mapWrap: { height: 300, marginHorizontal: SPACING.md, borderRadius: RADIUS.lg, overflow: 'hidden' },
  list: { flex: 1, paddingHorizontal: SPACING.md },
  section: { fontSize: 14, fontWeight: '800', color: COLORS.deepNavy, marginTop: SPACING.md, marginBottom: 6 },
  muted: { fontSize: 12, color: COLORS.textSecondary },
  busRow: { flexDirection: 'row', alignItems: 'center', minHeight: 44 },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 8 },
  busText: { flex: 1, fontSize: 13, color: COLORS.textPrimary },
  buyBtn: { minHeight: 48, marginTop: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.deepNavy, flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  buyText: { color: COLORS.textInverse, fontWeight: '800', fontSize: 15 },
  stopRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  seq: { width: 32, fontWeight: '800', color: COLORS.primaryDark },
  stopName: { fontSize: 14, color: COLORS.textPrimary },
  stopKn: { fontSize: 12, color: COLORS.textSecondary },
});
