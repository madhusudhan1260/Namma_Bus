import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useNetworkVehicles } from '../../hooks/useNetworkVehicles';
import { CITY_CENTRE, Coords, distanceMeters, positionIfGranted, requestPosition } from '../access/location';
import { freshnessColor } from './networkMapShared';

const RADIUS_KM = 2;
const LIST_SIZE = 8; // rows shown on Home; the map shows every bus

/**
 * Home: real BMTC buses closest to the user (from the same shared poll as the map — no extra requests).
 * Without location permission it uses Bengaluru city centre and says so.
 */
export function NearbyLiveBuses() {
  const router = useRouter();
  const { a } = useAccessT();
  const { data, vehicles, loading, error } = useNetworkVehicles();
  const [pos, setPos] = useState<Coords | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    positionIfGranted().then(setPos);
  }, []);

  const origin = pos || CITY_CENTRE;
  const nearby = useMemo(
    () =>
      vehicles
        .map(v => ({ v, d: distanceMeters(origin, { latitude: v.latitude, longitude: v.longitude }) }))
        .filter(x => x.d <= RADIUS_KM * 1000)
        .sort((x, y) => x.d - y.d),
    [vehicles, origin.latitude, origin.longitude] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const ask = async () => {
    setAsking(true);
    setPos(await requestPosition());
    setAsking(false);
  };

  const fresh = (f: string) => (f === 'LIVE' ? 'Live' : f === 'RECENT' ? 'Recent' : 'Stale');

  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <Text style={styles.title} accessibilityRole="header">{a('nearbyLiveTitle')}</Text>
        <TouchableOpacity onPress={() => router.push('/(tabs)/map' as any)} accessibilityRole="link">
          <Text style={styles.link}>{a('nearbyViewMap')}</Text>
        </TouchableOpacity>
      </View>
      {!pos ? (
        <View style={styles.notice}>
          <Text style={styles.noticeText}>{a('nearbyUsingCentre')}</Text>
          <TouchableOpacity style={styles.locBtn} onPress={ask} accessibilityRole="button">
            {asking ? <ActivityIndicator size="small" color={COLORS.primaryDark} /> : <Ionicons name="locate" size={16} color={COLORS.primaryDark} />}
            <Text style={styles.locText}>{a('nearbyAllowLocation')}</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {loading && !vehicles.length ? (
        <View style={styles.skeleton} accessibilityLabel={a('loading')}>
          {[0, 1, 2].map(i => <View key={i} style={styles.skelRow} />)}
        </View>
      ) : !data?.live_connected && !vehicles.length ? (
        <Text style={styles.empty}>{a('nearbyUnavailable')}{data?.operational_statement ? `\n${data.operational_statement}` : error ? `\n${error}` : ''}</Text>
      ) : nearby.length === 0 ? (
        <Text style={styles.empty}>{a('nearbyNone', { km: RADIUS_KM })}</Text>
      ) : (
        nearby.slice(0, LIST_SIZE).map(({ v, d }) => (
          <TouchableOpacity
            key={v.vehicle_id}
            style={styles.row}
            onPress={() => router.push({ pathname: '/(tabs)/map', params: { vehicle: v.vehicle_id } } as any)}
            accessibilityRole="button"
            accessibilityLabel={`${v.route_number} ${v.vehicle_number || ''} ${v.destination || ''}, ${a('nearbyAway', { m: d })}, ${fresh(v.freshness)}`}
          >
            <View style={styles.badge}>
              <Text style={styles.badgeText} numberOfLines={1}>{v.route_number || '—'}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.dest} numberOfLines={1}>{v.destination ? a('towards', { place: v.destination }) : v.vehicle_number}</Text>
              <Text style={styles.meta} numberOfLines={1}>
                {v.vehicle_number} · {a('nearbyAway', { m: d })}
                {v.next_stop?.stop_name ? ` · ${a('nearbyNext', { stop: v.next_stop.stop_name })}` : ''}
              </Text>
            </View>
            <View style={[styles.fresh, { backgroundColor: freshnessColor(v.freshness) }]}>
              <Text style={styles.freshText}>{fresh(v.freshness)}</Text>
            </View>
          </TouchableOpacity>
        ))
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginHorizontal: SPACING.md, marginBottom: SPACING.lg },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  title: { fontSize: 18, fontWeight: '800', color: COLORS.textPrimary },
  link: { color: COLORS.primaryDark, fontWeight: '800' },
  notice: { backgroundColor: COLORS.surfaceSubtle, borderRadius: RADIUS.md, padding: SPACING.sm, marginBottom: SPACING.sm },
  noticeText: { fontSize: 12, color: COLORS.textSecondary },
  locBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, marginTop: 4 },
  locText: { color: COLORS.primaryDark, fontWeight: '800' },
  skeleton: { gap: SPACING.sm },
  skelRow: { height: 56, borderRadius: RADIUS.md, backgroundColor: COLORS.surfaceSubtle },
  empty: { color: COLORS.textSecondary, fontSize: 13, lineHeight: 19 },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, minHeight: 60, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.sm, marginBottom: SPACING.xs || 6 },
  badge: { backgroundColor: COLORS.deepNavy, borderRadius: RADIUS.sm, paddingHorizontal: 8, paddingVertical: 4, maxWidth: 96 },
  badgeText: { color: COLORS.textInverse, fontWeight: '900', fontSize: 13 },
  dest: { fontWeight: '700', color: COLORS.textPrimary },
  meta: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  fresh: { borderRadius: RADIUS.full, paddingHorizontal: 8, paddingVertical: 2 },
  freshText: { color: '#FFFFFF', fontSize: 11, fontWeight: '800' },
});
