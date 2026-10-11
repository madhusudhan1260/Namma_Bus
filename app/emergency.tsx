import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Linking, Platform, Share, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { Facility, NetworkApi } from '../services/networkApi';
import { Coords, positionIfGranted, requestPosition } from '../components/access/location';
import { useReducedMotion } from '../components/access/useReducedMotion';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { FACILITY } from '../components/feature/facilityMeta';
import NetworkMap from '../components/network/NetworkMap';
import { FadeIn, PressScale, Skeleton, stagger } from '../components/ui/motion';

const RED = '#E11D48';
const native = Platform.OS !== 'web';
// National emergency numbers in India (well established). BMTC's own helpline is not listed here because we
// could not verify it from an official source inside the app.
const NUMBERS: { num: string; label: string; icon: keyof typeof Ionicons.glyphMap; color: string }[] = [
  { num: '108', label: 'emAmbulance', icon: 'medkit', color: '#DC2626' },
  { num: '100', label: 'emPolice', icon: 'shield', color: '#1E3A8A' },
  { num: '101', label: 'emFire', icon: 'flame', color: '#EA580C' },
  { num: '181', label: 'emWomen', icon: 'woman', color: '#B1285F' },
  { num: '1098', label: 'emChild', icon: 'happy', color: '#0EA5E9' },
];

const call = (n: string) => Linking.openURL(`tel:${n}`).catch(() => undefined);

/** Emergency: one-tap calls, share live location, and the nearest hospitals and police stations. */
export default function EmergencyScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const reduced = useReducedMotion();
  const [pos, setPos] = useState<Coords | null>(null);
  const [places, setPlaces] = useState<Facility[] | null>(null);
  const [placesMsg, setPlacesMsg] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [shared, setShared] = useState<string | null>(null);
  const ring = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(Animated.timing(ring, { toValue: 1, duration: 1600, easing: Easing.out(Easing.quad), useNativeDriver: native }));
    loop.start();
    return () => loop.stop();
  }, [ring, reduced]);

  useEffect(() => {
    positionIfGranted().then(p => p && setPos(p));
  }, []);
  useEffect(() => {
    if (!pos) return;
    setPlaces(null);
    NetworkApi.facilitiesNear(pos.latitude, pos.longitude, 3000, 'HOSPITAL,POLICE')
      .then(r => { setPlaces(r.places); setPlacesMsg(r.available ? null : r.message || null); })
      .catch(e => { setPlaces([]); setPlacesMsg(e.message); });
  }, [pos]);

  const locate = async () => {
    setLocating(true);
    const p = await requestPosition();
    setLocating(false);
    if (p) setPos(p);
    else setShared(a('mapLocationDenied'));
    return p;
  };
  const shareLocation = async () => {
    const p = pos || (await locate());
    if (!p) return;
    const link = `https://maps.google.com/?q=${p.latitude.toFixed(6)},${p.longitude.toFixed(6)}`;
    try {
      await Share.share({ message: `${a('emShareText')} ${link}` });
      setShared(a('emShared'));
    } catch {
      setShared(link);
    }
  };

  const pois = useMemo(
    () => (places || []).slice(0, 25).map(p => ({ id: p.id, latitude: p.latitude, longitude: p.longitude, label: p.name || a(FACILITY[p.category].label as any),
      emoji: FACILITY[p.category].emoji, color: FACILITY[p.category].color })),
    [places, a]
  );

  return (
    <FeatureShell
      title={a('tileEmergency')}
      icon="alert-circle-outline"
      color={RED}
      renderMap={mapType => <NetworkMap vehicles={[]} selectedVehicleId={null} mapType={mapType} pois={pois} userLocation={pos} focus={pos} />}
    >
      {/* SOS */}
      <PressScale hoverLift={false} onPress={() => call('112')} style={styles.sos} accessibilityRole="button" accessibilityLabel={a('emCall112')}>
        <View style={styles.sosIconWrap}>
          <Animated.View style={[styles.sosRing, { opacity: ring.interpolate({ inputRange: [0, 1], outputRange: [0.6, 0] }), transform: [{ scale: ring.interpolate({ inputRange: [0, 1], outputRange: [1, 1.9] }) }] }]} />
          <View style={styles.sosIcon}><Ionicons name="call" size={30} color={RED} /></View>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.sosNum}>112</Text>
          <Text style={styles.sosText}>{a('emAllEmergencies')}</Text>
        </View>
        <Ionicons name="chevron-forward" size={22} color="#FFFFFF" />
      </PressScale>

      <View style={styles.grid}>
        {NUMBERS.map((n, i) => (
          <FadeIn key={n.num} delay={stagger(i, 60)} style={styles.cell}>
            <PressScale onPress={() => call(n.num)} style={styles.numCard} accessibilityRole="button" accessibilityLabel={`${a(n.label as any)} ${n.num}`}>
              <View style={[styles.numIcon, { backgroundColor: n.color }]}><Ionicons name={n.icon} size={20} color="#FFFFFF" /></View>
              <Text style={styles.numText}>{n.num}</Text>
              <Text style={styles.numLabel} numberOfLines={2}>{a(n.label as any)}</Text>
            </PressScale>
          </FadeIn>
        ))}
      </View>

      <GradientButton label={a('emShareLocation')} icon="share-social-outline" onPress={shareLocation} busy={locating} />
      {shared ? <Text style={styles.small}>{shared}</Text> : null}

      <Text style={styles.section}>{a('emNearest')}</Text>
      {!pos ? (
        <PressScale hoverLift={false} style={styles.locBtn} onPress={locate} accessibilityRole="button">
          <Ionicons name="locate" size={18} color="#B1285F" />
          <Text style={styles.locText}>{a('emFindNearest')}</Text>
        </PressScale>
      ) : places === null ? (
        <View style={{ gap: 8 }}>{[0, 1, 2].map(i => <Skeleton key={i} height={58} radius={12} />)}</View>
      ) : null}
      {placesMsg ? <Text style={styles.small}>{placesMsg}</Text> : null}
      {places?.slice(0, 8).map((p, i) => (
        <FadeIn key={p.id} delay={stagger(i, 40)}>
          <View style={styles.place}>
            <View style={[styles.placeIcon, { borderColor: FACILITY[p.category].color }]}><Ionicons name={FACILITY[p.category].icon} size={18} color={FACILITY[p.category].color} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.placeName} numberOfLines={1}>{p.name || a(FACILITY[p.category].label as any)}</Text>
              <Text style={styles.placeMeta}>{a(FACILITY[p.category].label as any)} · {p.distance_m < 1000 ? `${p.distance_m} m` : `${(p.distance_m / 1000).toFixed(1)} km`}</Text>
            </View>
            {p.phone ? (
              <PressScale hoverLift={false} style={styles.callSmall} onPress={() => call(p.phone!.split(/[;,]/)[0].replace(/\s/g, ''))} accessibilityRole="button" accessibilityLabel={`${a('emCall')} ${p.name || ''}`}>
                <Ionicons name="call" size={16} color="#FFFFFF" />
              </PressScale>
            ) : null}
          </View>
        </FadeIn>
      ))}
      {places && !places.length && !placesMsg ? <Text style={styles.small}>{a('emNoneNearby')}</Text> : null}
      {places?.length ? <Text style={styles.source}>{a('facSource')}</Text> : null}

      <View style={styles.tip}>
        <Ionicons name="information-circle" size={20} color="#B1285F" />
        <Text style={styles.tipText}>{a('emTip')}</Text>
      </View>
      <PressScale hoverLift={false} style={styles.locBtn} onPress={() => router.push('/complaint' as any)} accessibilityRole="button">
        <Ionicons name="document-text-outline" size={18} color="#B1285F" />
        <Text style={styles.locText}>{a('emRaiseComplaint')}</Text>
      </PressScale>
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  sos: { flexDirection: 'row', alignItems: 'center', gap: 16, backgroundColor: RED, borderRadius: 18, padding: 18, shadowColor: RED, shadowOpacity: 0.35, shadowRadius: 12, shadowOffset: { width: 0, height: 6 } },
  sosIconWrap: { width: 60, height: 60, alignItems: 'center', justifyContent: 'center' },
  sosRing: { position: 'absolute', width: 60, height: 60, borderRadius: 30, backgroundColor: '#FFFFFF' },
  sosIcon: { width: 60, height: 60, borderRadius: 30, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  sosNum: { color: '#FFFFFF', fontSize: 34, fontWeight: '900', letterSpacing: 2 },
  sosText: { color: '#FFE4EA', fontWeight: '700' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 14, marginBottom: 6 },
  cell: { width: '31%' as any, flexGrow: 1 },
  numCard: { alignItems: 'center', borderWidth: 1, borderColor: '#EEE', borderRadius: 14, paddingVertical: 12, paddingHorizontal: 6, backgroundColor: '#FFFFFF' },
  numIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  numText: { fontSize: 20, fontWeight: '900', color: '#1E1E24', marginTop: 6 },
  numLabel: { fontSize: 12, color: '#555', textAlign: 'center' },
  small: { color: '#666', fontSize: 12, marginTop: 8 },
  section: { fontSize: 18, fontWeight: '800', color: '#1E1E24', marginTop: 22, marginBottom: 10 },
  locBtn: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 46, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1.5, borderColor: '#B1285F', alignSelf: 'flex-start', marginTop: 8 },
  locText: { color: '#B1285F', fontWeight: '800' },
  place: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 58, borderWidth: 1, borderColor: '#EEE', borderRadius: 12, paddingHorizontal: 12, marginTop: 8 },
  placeIcon: { width: 36, height: 36, borderRadius: 18, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  placeName: { fontWeight: '700', color: '#1E1E24' },
  placeMeta: { fontSize: 12, color: '#777', marginTop: 2 },
  callSmall: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#16A34A', alignItems: 'center', justifyContent: 'center' },
  source: { color: '#888', fontSize: 11, marginTop: 10 },
  tip: { flexDirection: 'row', gap: 10, backgroundColor: '#FFF1F5', borderRadius: 12, padding: 12, marginTop: 20 },
  tipText: { flex: 1, color: '#5B2140', fontSize: 13, lineHeight: 19 },
});
