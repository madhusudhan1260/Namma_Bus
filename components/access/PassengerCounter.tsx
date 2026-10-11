import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAccessT } from '../../constants/accessI18n';
import type { LiveTrip } from '../../services/accessApi';
import type { RealtimeStatus } from '../../services/realtime';
import { useReducedMotion } from './useReducedMotion';

const native = Platform.OS !== 'web';

const TONE = {
  AVAILABLE: { fg: '#0F7A3A', bg: '#E3F6EA', bar: '#1FA855', dot: '🟢' },
  FILLING: { fg: '#9A5A00', bg: '#FFF2DB', bar: '#F29D12', dot: '🟠' },
  FULL: { fg: '#B3141B', bg: '#FDE6E7', bar: '#E0262E', dot: '🔴' },
} as const;

function timeAgo(at: number | null, now: number): string {
  if (!at) return '—';
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)} min ago`;
}

/** Status of the live connection. Shown on every counter so a stale number is never mistaken for a live one. */
export function ConnectionBadge({ status }: { status: RealtimeStatus }) {
  const { a } = useAccessT();
  const map = {
    live: { label: a('rtLive'), color: '#0F7A3A', bg: '#E3F6EA', icon: 'radio-outline' },
    connecting: { label: a('rtConnecting'), color: '#44506A', bg: '#EEF0F4', icon: 'sync-outline' },
    reconnecting: { label: a('rtReconnecting'), color: '#9A5A00', bg: '#FFF2DB', icon: 'sync-outline' },
    offline: { label: a('rtOffline'), color: '#8E1C1C', bg: '#FDE8E8', icon: 'cloud-offline-outline' },
  } as const;
  const m = map[status];
  return (
    <View style={[styles.badge, { backgroundColor: m.bg }]} accessibilityLabel={m.label}>
      <Ionicons name={m.icon as any} size={13} color={m.color} />
      <Text style={[styles.badgeText, { color: m.color }]}>{m.label}</Text>
    </View>
  );
}

/**
 * Live passenger counter for one trip. Shows only what the backend sent — the number animates to each new
 * committed value; nothing is incremented on the device. `size="large"` is the conductor's one-hand view.
 */
export function PassengerCounter({ trip, status, lastUpdated, size = 'large', stops }: {
  trip: LiveTrip;
  /** Current / next stop from the real BMTC feed, when the bus is in it (never invented) */
  stops?: { current?: string | null; next?: string | null } | null;
  status: RealtimeStatus;
  lastUpdated: number | null;
  size?: 'large' | 'compact';
}) {
  const { a } = useAccessT();
  const reduced = useReducedMotion();
  const tone = TONE[trip.occupancy] || TONE.AVAILABLE;
  const pct = trip.max_capacity > 0 ? Math.min(1, trip.passenger_count / trip.max_capacity) : 1;

  // Count-up animation between confirmed values
  const value = useRef(new Animated.Value(trip.passenger_count)).current;
  const [shown, setShown] = useState(trip.passenger_count);
  const bump = useRef(new Animated.Value(1)).current;
  const bar = useRef(new Animated.Value(pct)).current;
  const prev = useRef(trip.passenger_count);
  useEffect(() => {
    const id = value.addListener(({ value: v }) => setShown(Math.round(v)));
    return () => value.removeListener(id);
  }, [value]);
  useEffect(() => {
    const changed = prev.current !== trip.passenger_count;
    prev.current = trip.passenger_count;
    if (reduced) {
      value.setValue(trip.passenger_count);
      bar.setValue(pct);
      return;
    }
    Animated.timing(value, { toValue: trip.passenger_count, duration: 450, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
    Animated.timing(bar, { toValue: pct, duration: 500, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
    if (changed) {
      bump.setValue(1.18);
      Animated.spring(bump, { toValue: 1, speed: 14, bounciness: 12, useNativeDriver: native }).start();
    }
  }, [trip.passenger_count, pct, reduced, value, bar, bump]);

  // "Last updated" ticks every few seconds
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);

  // FULL pulses gently
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (trip.occupancy !== 'FULL' || reduced) {
      pulse.setValue(0);
      return;
    }
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: native }),
      Animated.timing(pulse, { toValue: 0, duration: 700, useNativeDriver: native }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [trip.occupancy, reduced, pulse]);

  const large = size === 'large';
  const occLabel = trip.occupancy === 'FULL' ? a('rtFull') : trip.occupancy === 'FILLING' ? a('rtFilling') : a('rtPlenty');
  const pctOccupied = trip.max_capacity > 0 ? Math.round((trip.passenger_count / trip.max_capacity) * 100) : 100;
  const ended = trip.status !== 'ACTIVE';

  return (
    <View style={[styles.card, { borderColor: tone.bar }, !large && styles.cardCompact]}
      accessibilityRole="summary" accessibilityLiveRegion="polite"
      accessibilityLabel={`${a('rtOnBoard')}: ${trip.passenger_count} / ${trip.max_capacity}. ${occLabel}`}>
      <View style={styles.headRow}>
        <Text style={styles.tripCode} numberOfLines={1}>
          {a('rtTrip')} {trip.trip_code || trip.trip_id.slice(0, 8)}{trip.bus_label ? ` · ${trip.bus_label}` : ''}
        </Text>
        <ConnectionBadge status={status} />
      </View>

      <View style={styles.countRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.caption}>{a('rtOnBoard')}</Text>
          <View style={styles.numberLine}>
            <Animated.Text style={[styles.count, large ? styles.countLarge : styles.countCompact, { color: tone.fg, transform: [{ scale: bump }] }]}>
              {shown}
            </Animated.Text>
            <Text style={[styles.cap, !large && { fontSize: 15 }]}> / {trip.max_capacity}</Text>
          </View>
        </View>
        <Animated.View style={[styles.occ, { backgroundColor: tone.bg, opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 0.55] }) }]}>
          <Text style={[styles.occText, { color: tone.fg }, large && { fontSize: 18 }]}>{tone.dot} {ended ? a('rtTripEnded') : occLabel}</Text>
          <Text style={[styles.seats, { color: tone.fg }]}>{a('rtSeatsLeft', { n: trip.seats_left })}</Text>
          <Text style={[styles.seats, { color: tone.fg, opacity: 0.85 }]}>{a('rtOccupied', { pct: pctOccupied })}</Text>
        </Animated.View>
      </View>

      {stops && (stops.current || stops.next) ? (
        <View style={styles.stopsRow}>
          <Text style={styles.stopLine} numberOfLines={1}>{a('currentStop')}: <Text style={styles.stopName}>{stops.current || '—'}</Text></Text>
          <Text style={styles.stopLine} numberOfLines={1}>{a('nextStop')}: <Text style={styles.stopName}>{stops.next || '—'}</Text></Text>
        </View>
      ) : null}
      <View style={styles.track}>
        <Animated.View style={[styles.fill, { backgroundColor: tone.bar, width: bar.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} />
      </View>
      <Text style={styles.updated}>{a('rtUpdated', { t: timeAgo(lastUpdated, now) })}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: '#FFFFFF', borderRadius: 18, borderWidth: 2, padding: 16, marginBottom: 14,
    shadowColor: '#3B0A24', shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 3 },
  cardCompact: { padding: 12, borderRadius: 14 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  tripCode: { flex: 1, fontSize: 12, fontWeight: '800', color: '#5F6B76', letterSpacing: 0.3 },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999 },
  badgeText: { fontSize: 11, fontWeight: '800' },
  countRow: { flexDirection: 'row', alignItems: 'center', marginTop: 8, gap: 10, flexWrap: 'wrap' },
  caption: { fontSize: 13, fontWeight: '700', color: '#5F6B76' },
  numberLine: { flexDirection: 'row', alignItems: 'flex-end' },
  count: { fontWeight: '900', fontVariant: ['tabular-nums'] },
  countLarge: { fontSize: 72, lineHeight: 80 },
  countCompact: { fontSize: 36, lineHeight: 42 },
  cap: { fontSize: 22, fontWeight: '800', color: '#8A959F', marginBottom: 10 },
  occ: { borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10, alignItems: 'center', minWidth: 130 },
  occText: { fontSize: 15, fontWeight: '900' },
  seats: { fontSize: 12, fontWeight: '700', marginTop: 2 },
  track: { height: 12, borderRadius: 6, backgroundColor: '#EEF0F4', overflow: 'hidden', marginTop: 12 },
  fill: { height: '100%', borderRadius: 6 },
  stopsRow: { marginTop: 10, gap: 2 },
  stopLine: { fontSize: 13, color: '#5F6B76' },
  stopName: { fontWeight: '800', color: '#17212B' },
  updated: { fontSize: 12, color: '#8A959F', marginTop: 8 },
});
