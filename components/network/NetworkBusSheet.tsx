import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { t, TranslationKey } from '../../constants/i18n';
import { NetworkVehicle } from '../../types/network';
import { freshnessColor } from './networkMapShared';
import { PassengerCounter } from '../access/PassengerCounter';
import { useLiveTrips } from '../../hooks/useLiveTrips';
import { AccessApi, loadSession } from '../../services/accessApi';
import { normRoute } from '../../services/realtime';

type Lang = 'EN' | 'KN';

const FRESH_KEY: Record<string, TranslationKey> = { LIVE: 'freshnessLive', RECENT: 'freshnessRecent', STALE: 'freshnessStale' };

/**
 * Selected BMTC bus. The parent passes the vehicle looked up by id from the LATEST poll, so switching
 * buses (or a new poll) never shows the previous bus's data. `missing` = selected bus left the feed.
 */
export function NetworkBusSheet({ vehicle, missing, lang, onClose }: { vehicle: NetworkVehicle | null; missing?: boolean; lang: Lang; onClose: () => void }) {
  const router = useRouter();
  if (!vehicle) {
    if (!missing) return null;
    return (
      <View style={styles.sheet} accessibilityLiveRegion="polite">
        <Text style={styles.muted}>{t('netBusGone', lang)}</Text>
        <CloseBtn lang={lang} onClose={onClose} />
      </View>
    );
  }
  const route = vehicle.route_number || '—';
  const fresh = `${t(FRESH_KEY[vehicle.freshness], lang)}${vehicle.freshness_seconds != null ? ` · ${vehicle.freshness_seconds}${t('freshnessAgeSuffix', lang)}` : ''}`;
  const progress = vehicle.progress_percentage;

  return (
    <View style={styles.sheet} accessible={false}>
      <View style={styles.headRow}>
        <View style={styles.routeBadge}>
          <Text style={styles.routeBadgeText}>{route}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>
            {t('netBus', lang)} {vehicle.vehicle_number || vehicle.vehicle_id}
          </Text>
          {vehicle.destination ? (
            <Text style={styles.sub} numberOfLines={1}>
              {vehicle.origin ? `${vehicle.origin} → ` : ''}{t('rtTowards', lang)} {vehicle.destination}
            </Text>
          ) : null}
        </View>
        <CloseBtn lang={lang} onClose={onClose} />
      </View>

      <View style={styles.chips}>
        <View style={[styles.chip, { backgroundColor: freshnessColor(vehicle.freshness) }]} accessible accessibilityLabel={fresh}>
          <Text style={styles.chipTextLight}>{fresh}</Text>
        </View>
        <View style={[styles.chip, { backgroundColor: COLORS.surfaceSubtle }]}>
          <Text style={styles.chipText}>{t('netSource', lang)}</Text>
        </View>
      </View>

      <Row label={t('rtCurrentStop', lang)} value={vehicle.current_stop?.stop_name || t('rtUnknown', lang)} />
      <Row
        label={t('rtNextStop', lang)}
        value={vehicle.next_stop?.stop_name ? `${vehicle.next_stop.stop_name}${vehicle.next_stop.distance_meters != null ? ` · ${vehicle.next_stop.distance_meters} m` : ''}` : t('rtUnknown', lang)}
      />
      <Row label={t('netCompletedStops', lang)} value={vehicle.completed_stops != null ? String(vehicle.completed_stops) : t('rtUnknown', lang)} />
      <Row label={t('netRemainingStops', lang)} value={vehicle.remaining_stops != null ? String(vehicle.remaining_stops) : t('rtUnknown', lang)} />
      {progress != null ? (
        <View accessible accessibilityLabel={`${t('netProgress', lang)} ${progress}%`}>
          <Text style={styles.label}>{t('netProgress', lang)} · {progress}%</Text>
          <View style={styles.track}>
            <View style={[styles.fill, { width: `${Math.min(100, Math.max(0, progress))}%` }]} />
          </View>
        </View>
      ) : null}

      {vehicle.route_number && vehicle.vehicle_number ? <SheetCapacity route={vehicle.route_number} vehicleNumber={vehicle.vehicle_number} /> : null}

      <View style={styles.actions}>
        {vehicle.route_number ? (
          <Action icon="git-branch-outline" label={t('netRouteDetails', lang)} onPress={() => router.push({ pathname: '/network/route/[route]', params: { route: vehicle.route_number!, vehicle: vehicle.vehicle_id } } as any)} />
        ) : null}
        {vehicle.route_number ? (
          <Action
            icon="card-outline"
            label={t('netBuyTicket', lang)}
            onPress={() => router.push({ pathname: '/access/buy', params: { route: vehicle.route_number!, vehicle: vehicle.vehicle_number || vehicle.vehicle_id, direction: String(vehicle.direction ?? 0) } } as any)}
          />
        ) : null}
      </View>
    </View>
  );
}

/**
 * Passengers on board for this bus — only when this BMTC vehicle (matched by registration number) has a running
 * Namma Bus trip. Counts come from the backend; for signed-in users only; nothing is shown otherwise.
 */
function SheetCapacity({ route, vehicleNumber }: { route: string; vehicleNumber: string }) {
  const [tripId, setTripId] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setTripId(null);
    loadSession().then(sess => {
      if (!sess || !alive) return;
      AccessApi.tripsActive(route)
        .then(r => alive && setTripId(r.trips.find(t => normRoute(t.vehicle_number) === normRoute(vehicleNumber))?.trip_id ?? null))
        .catch(() => undefined);
    });
    return () => {
      alive = false;
    };
  }, [route, vehicleNumber]);
  const live = useLiveTrips(tripId ? `trip:${tripId}` : null);
  if (!live.trip) return null;
  return <View style={{ marginTop: SPACING.sm }}><PassengerCounter trip={live.trip} status={live.status} lastUpdated={live.lastUpdated} size="compact" /></View>;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Action({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.action} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={16} color={COLORS.primaryDark} style={{ marginRight: 6 }} />
      <Text style={styles.actionText}>{label}</Text>
    </TouchableOpacity>
  );
}

function CloseBtn({ lang, onClose }: { lang: Lang; onClose: () => void }) {
  return (
    <TouchableOpacity onPress={onClose} style={styles.close} accessibilityRole="button" accessibilityLabel={t('netClose', lang)}>
      <Ionicons name="close" size={22} color={COLORS.textSecondary} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: COLORS.surface,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
  },
  headRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  routeBadge: { backgroundColor: COLORS.deepNavy, borderRadius: RADIUS.md, paddingHorizontal: 10, paddingVertical: 6 },
  routeBadgeText: { color: COLORS.textInverse, fontWeight: '900', fontSize: 15 },
  title: { fontSize: 16, fontWeight: '800', color: COLORS.textPrimary },
  sub: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginVertical: SPACING.sm },
  chip: { borderRadius: RADIUS.full, paddingHorizontal: 10, paddingVertical: 3 },
  chipText: { fontSize: 11, fontWeight: '800', color: COLORS.textSecondary },
  chipTextLight: { fontSize: 11, fontWeight: '800', color: '#FFFFFF' },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, gap: SPACING.sm },
  label: { fontSize: 13, color: COLORS.textSecondary },
  value: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary, flexShrink: 1, textAlign: 'right' },
  track: { height: 6, borderRadius: 3, backgroundColor: COLORS.surfaceSubtle, marginTop: 4, overflow: 'hidden' },
  fill: { height: 6, backgroundColor: COLORS.primary },
  actions: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.md },
  action: {
    flex: 1,
    minHeight: 44,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionText: { color: COLORS.primaryDark, fontWeight: '700' },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  muted: { color: COLORS.textSecondary, fontSize: 13 },
});
