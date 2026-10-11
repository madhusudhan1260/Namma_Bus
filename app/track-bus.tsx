import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAccessT } from '../constants/accessI18n';
import { useNetworkVehicles } from '../hooks/useNetworkVehicles';
import { useRecentSearches } from '../hooks/useRecentSearches';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OutlinedInput, RecentList } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import { LiveBusesMap } from '../components/feature/LiveBusesMap';
import { FadeIn, PressScale, stagger } from '../components/ui/motion';

const norm = (s: string) => s.replace(/[\s-]/g, '').toUpperCase();
const FRESH_COLOR: Record<string, string> = { LIVE: '#168A45', RECENT: '#C47A00', STALE: '#8A959F' };

/** Track a Bus: type a registration number; every live bus is on the map, matching buses are listed. */
export default function TrackBusScreen() {
  const { a } = useAccessT();
  const { data, vehicles, loading } = useNetworkVehicles(undefined, 15000);
  const recent = useRecentSearches<{ key: string; label: string }>('track-bus');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const q = norm(query);
  const matches = useMemo(() => (q.length >= 3 ? vehicles.filter(v => norm(v.vehicle_number || '').includes(q)).slice(0, 12) : []), [vehicles, q]);

  const pick = (id: string) => {
    const v = vehicles.find(x => x.vehicle_id === id);
    setSelected(id);
    if (v?.vehicle_number) recent.add({ key: norm(v.vehicle_number), label: v.vehicle_number });
  };

  return (
    <FeatureShell
      title={a('tileTrackBus')}
      icon="bus-outline"
      color="#EF7D12"
      renderMap={mapType => (
        <LiveBusesMap vehicles={vehicles} live={!!data?.live_connected} mapType={mapType} selectedId={selected} onSelect={setSelected} />
      )}
    >
      <Text style={styles.label}>{a('fsEnterBusNumber')}</Text>
      <OutlinedInput value={query} onChangeText={t => { setQuery(t); setSelected(null); }} placeholder="Eg: KA 57 F 4578" autoCapitalize="characters" autoFocus
        onSubmit={() => matches[0] && pick(matches[0].vehicle_id)} />
      {matches.length ? <GradientButton label={a('fsTrack')} icon="locate" onPress={() => pick(matches[0].vehicle_id)} /> : null}

      {matches.map((v, i) => (
        <FadeIn key={v.vehicle_id} delay={stagger(i, 50)}>
          <PressScale hoverLift={false} style={[styles.bus, selected === v.vehicle_id && styles.busOn]} onPress={() => pick(v.vehicle_id)} accessibilityRole="button"
            accessibilityLabel={`${v.vehicle_number}, ${a('route')} ${v.route_number}`}>
            <View style={[styles.busIcon, { backgroundColor: FRESH_COLOR[v.freshness] || '#8A959F' }]}><Ionicons name="bus" size={20} color="#FFFFFF" /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.busNo}>{v.vehicle_number}</Text>
              <Text style={styles.busMeta} numberOfLines={2}>
                {a('route')} {v.route_number || '—'}{v.destination ? ` · ${a('ttTowards', { place: v.destination })}` : ''}
                {v.next_stop?.stop_name ? `\n${a('nextStop')}: ${v.next_stop.stop_name}` : ''}
              </Text>
            </View>
            <Text style={[styles.fresh, { color: FRESH_COLOR[v.freshness] }]}>{v.freshness}</Text>
          </PressScale>
        </FadeIn>
      ))}

      {q.length >= 3 && !matches.length && !loading ? (
        <EmptyState title={a('fsNoBusTitle')} message={data?.live_connected ? a('fsNoBusMsg') : a('mapFeedUnavailable')} />
      ) : null}
      {q.length < 3 ? (
        <>
          <EmptyState title={a('fsTrackBusHintTitle')} message={a('fsTrackBusHint', { n: vehicles.length })} />
          <RecentList title={a('fsRecent')} items={recent.items} icon="bus-outline" onClear={recent.clear} clearLabel={a('fsClear')}
            onPick={k => { const r = recent.items.find(x => x.key === k); if (r) setQuery(r.label); }} />
        </>
      ) : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 16, fontWeight: '700', color: '#55565C', marginBottom: 12 },
  bus: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 14, padding: 12, marginTop: 12, backgroundColor: '#FFFFFF' },
  busOn: { borderColor: '#EF7D12', borderWidth: 2, backgroundColor: '#FFF8F1' },
  busIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  busNo: { fontWeight: '900', fontSize: 16, color: '#1E1E24', letterSpacing: 0.5 },
  busMeta: { color: '#666', fontSize: 12, marginTop: 2, lineHeight: 17 },
  fresh: { fontSize: 11, fontWeight: '900' },
});
