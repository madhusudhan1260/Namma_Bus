import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAccessT } from '../constants/accessI18n';
import { FacilitiesResponse, FacilityCategory, NetworkApi } from '../services/networkApi';
import { FeatureShell } from '../components/feature/FeatureShell';
import { OutlinedInput } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import { FACILITY, FACILITY_ORDER } from '../components/feature/facilityMeta';
import NetworkMap from '../components/network/NetworkMap';
import { FadeIn, PressScale, Skeleton, stagger } from '../components/ui/motion';

type Station = FacilitiesResponse['stations'][number];

/** Facilities near major bus stations (toilets, medical stores, ATMs, water, parking, police, hospitals, food) from OpenStreetMap. */
export default function FacilitiesScreen() {
  const { a } = useAccessT();
  const [data, setData] = useState<FacilitiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [cat, setCat] = useState<FacilityCategory | null>(null);
  const [station, setStation] = useState<Station | null>(null);
  const [focus, setFocus] = useState<{ latitude: number; longitude: number } | null>(null);

  const load = () => {
    setError(null);
    NetworkApi.facilities().then(setData).catch(e => setError(e.message));
  };
  useEffect(load, []);

  const stations = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.stations || []).filter(s => (!q || s.name.toLowerCase().includes(q)) && (!cat || (s.counts[cat] || 0) > 0));
  }, [data, query, cat]);

  const shownFacilities = useMemo(() => (station ? station.facilities.filter(f => !cat || f.category === cat) : []), [station, cat]);
  const pois = useMemo(() => {
    if (station) {
      return [
        { id: 'station', latitude: station.latitude, longitude: station.longitude, label: station.name, emoji: '🚏', color: '#B1285F' },
        ...shownFacilities.map(f => ({ id: f.id, latitude: f.latitude, longitude: f.longitude, label: `${a(FACILITY[f.category].label as any)}${f.name ? `: ${f.name}` : ''}`,
          emoji: FACILITY[f.category].emoji, color: FACILITY[f.category].color })),
      ];
    }
    return stations.map(s => ({ id: `st:${s.name}`, latitude: s.latitude, longitude: s.longitude, label: s.name, emoji: '🚏', color: '#B1285F' }));
  }, [station, shownFacilities, stations, a]);

  return (
    <FeatureShell
      title={a('tileFacilities')}
      icon="business-outline"
      color="#F0506E"
      renderMap={mapType => (
        <NetworkMap vehicles={[]} selectedVehicleId={null} mapType={mapType} pois={pois} focus={focus}
          onSelectPoi={id => {
            const s = (data?.stations || []).find(x => `st:${x.name}` === id);
            if (s) { setStation(s); setFocus(null); }
          }} />
      )}
    >
      <OutlinedInput value={query} onChangeText={setQuery} placeholder={a('facSearch')} autoCapitalize="words"
        right={<Ionicons name="search" size={18} color="#888" style={{ marginRight: 12 }} />} />
      <View style={styles.cats}>
        {FACILITY_ORDER.map(c => (
          <PressScale key={c} hoverLift={false} style={[styles.cat, cat === c && { backgroundColor: FACILITY[c].color, borderColor: FACILITY[c].color }]}
            onPress={() => setCat(cat === c ? null : c)} accessibilityRole="checkbox" accessibilityState={{ checked: cat === c }} accessibilityLabel={a(FACILITY[c].label as any)}>
            <Ionicons name={FACILITY[c].icon} size={15} color={cat === c ? '#FFFFFF' : FACILITY[c].color} />
            <Text style={[styles.catText, cat === c && { color: '#FFFFFF' }]}>{a(FACILITY[c].label as any)}</Text>
          </PressScale>
        ))}
      </View>

      {!data && !error ? (
        <View style={{ gap: 12, marginTop: 8 }}>
          <View style={styles.loadingRow}><ActivityIndicator color="#F0506E" /><Text style={styles.muted}>{a('facLoading')}</Text></View>
          {[0, 1, 2, 3].map(i => <Skeleton key={i} height={84} radius={12} />)}
        </View>
      ) : null}
      {error || (data && !data.available) ? (
        <>
          <EmptyState compact title={a('facUnavailableTitle')} message={data?.message || error || ''} />
          <PressScale hoverLift={false} style={styles.retry} onPress={load} accessibilityRole="button"><Text style={styles.retryText}>{a('tryAgain')}</Text></PressScale>
        </>
      ) : null}

      {station ? (
        <FadeIn key={station.name}>
          <PressScale hoverLift={false} style={styles.back} onPress={() => setStation(null)} accessibilityRole="button">
            <Ionicons name="chevron-back" size={18} color="#B1285F" /><Text style={styles.backText}>{a('facAllStations')}</Text>
          </PressScale>
          <View style={styles.stationHead}>
            <Text style={{ fontSize: 20 }}>🚏</Text>
            <Text style={styles.stationTitle}>{station.name}</Text>
          </View>
          <Text style={styles.muted}>{a('facWithin', { m: data?.radius_m || 350 })}</Text>
          {!shownFacilities.length ? <Text style={styles.muted}>{a('facNoneHere')}</Text> : null}
          {shownFacilities.map((f, i) => (
            <FadeIn key={f.id} delay={stagger(i, 35)}>
              <PressScale hoverLift={false} style={styles.fac} onPress={() => setFocus({ latitude: f.latitude, longitude: f.longitude })} accessibilityRole="button">
                <View style={[styles.facIcon, { borderColor: FACILITY[f.category].color }]}><Ionicons name={FACILITY[f.category].icon} size={18} color={FACILITY[f.category].color} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.facName} numberOfLines={1}>{f.name || a(FACILITY[f.category].label as any)}</Text>
                  <Text style={styles.facMeta} numberOfLines={1}>{a(FACILITY[f.category].label as any)} · {f.distance_m} m{f.opening_hours ? ` · ${f.opening_hours}` : ''}</Text>
                </View>
              </PressScale>
            </FadeIn>
          ))}
        </FadeIn>
      ) : (
        stations.map((s, i) => (
          <FadeIn key={s.name} delay={stagger(i, 40)}>
            <PressScale hoverLift={false} style={styles.station} onPress={() => { setStation(s); setFocus(null); }} accessibilityRole="button"
              accessibilityLabel={`${s.name}: ${Object.entries(s.counts).map(([k, n]) => `${n} ${a(FACILITY[k as FacilityCategory].label as any)}`).join(', ')}`}>
              <View style={styles.stationHead}>
                <Ionicons name="business-outline" size={18} color="#888" />
                <Text style={styles.stationName} numberOfLines={1}>{s.name}</Text>
              </View>
              <View style={styles.icons}>
                {FACILITY_ORDER.filter(c => (s.counts[c] || 0) > 0).map(c => (
                  <View key={c} style={[styles.iconCircle, { borderColor: `${FACILITY[c].color}66` }]}>
                    <Ionicons name={FACILITY[c].icon} size={18} color={FACILITY[c].color} />
                    <Text style={[styles.iconCount, { backgroundColor: FACILITY[c].color }]}>{s.counts[c]}</Text>
                  </View>
                ))}
                {!Object.keys(s.counts).length ? <Text style={styles.muted}>{a('facNoneMapped')}</Text> : null}
              </View>
            </PressScale>
          </FadeIn>
        ))
      )}
      {data?.available ? <Text style={styles.source}>{a('facSource')}</Text> : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  cats: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginVertical: 14 },
  cat: { flexDirection: 'row', alignItems: 'center', gap: 5, minHeight: 34, paddingHorizontal: 10, borderRadius: 17, borderWidth: 1.2, borderColor: '#DDD', backgroundColor: '#FFFFFF' },
  catText: { fontSize: 12, fontWeight: '700', color: '#333' },
  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  station: { paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#EEE' },
  stationHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  stationName: { flex: 1, fontSize: 16, fontWeight: '700', color: '#1E1E24' },
  stationTitle: { flex: 1, fontSize: 18, fontWeight: '800', color: '#1E1E24' },
  icons: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 10 },
  iconCircle: { width: 44, height: 44, borderRadius: 22, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  iconCount: { position: 'absolute', top: -4, right: -6, minWidth: 18, height: 18, borderRadius: 9, color: '#FFFFFF', fontSize: 10, fontWeight: '900',
    textAlign: 'center', lineHeight: 18, overflow: 'hidden', paddingHorizontal: 3 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 40, alignSelf: 'flex-start' },
  backText: { color: '#B1285F', fontWeight: '800' },
  fac: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 58, borderWidth: 1, borderColor: '#EEE', borderRadius: 12, paddingHorizontal: 12, marginTop: 8 },
  facIcon: { width: 36, height: 36, borderRadius: 18, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  facName: { fontWeight: '700', color: '#1E1E24' },
  facMeta: { fontSize: 12, color: '#777', marginTop: 2 },
  muted: { color: '#777', fontSize: 13, marginTop: 6 },
  source: { color: '#888', fontSize: 11, marginTop: 16, lineHeight: 16 },
  retry: { alignSelf: 'center', minHeight: 42, paddingHorizontal: 20, borderRadius: 21, borderWidth: 1.5, borderColor: '#B1285F', justifyContent: 'center' },
  retryText: { color: '#B1285F', fontWeight: '800' },
});
