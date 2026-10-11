import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { NetworkApi } from '../services/networkApi';
import { useRecentSearches } from '../hooks/useRecentSearches';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OriginDestination, RecentList } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import NetworkMap from '../components/network/NetworkMap';
import { FadeIn, PressScale, Skeleton, stagger } from '../components/ui/motion';

type Estimate = Awaited<ReturnType<typeof NetworkApi.fareEstimate>>;
const OLIVE = '#9AA23A';
const LEG_COLORS = ['#1976D2', '#F28C28', '#7B3FB8'];
const CATS = [['ADULT', 'catAdult', '#12355B'], ['CHILD', 'catChild', '#1FBF7F'], ['SENIOR', 'catSenior', '#EF7D12']] as const;

/** Fare Calculator: BMTC stage fares (Adult / Child / Senior) for journey options between two places. */
export default function FareCalculatorScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const params = useLocalSearchParams<{ from?: string; to?: string }>();
  const recent = useRecentSearches<{ key: string; from: string; to: string }>('fare');
  const [from, setFrom] = useState(typeof params.from === 'string' ? params.from : '');
  const [to, setTo] = useState(typeof params.to === 'string' ? params.to : '');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState(0);
  const [lines, setLines] = useState<{ coords: [number, number][]; color?: string }[]>([]);

  const calc = async (f = from, t = to) => {
    if (f.trim().length < 2 || t.trim().length < 2 || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setPicked(0);
    try {
      setResult(await NetworkApi.fareEstimate(f.trim(), t.trim()));
      recent.add({ key: `${f.trim()}→${t.trim()}`.toLowerCase(), from: f.trim(), to: t.trim() });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (from && to && params.from) calc(from, to);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw the chosen option's routes
  useEffect(() => {
    setLines([]);
    const option = result?.options[picked];
    if (!option) return;
    Promise.all(option.legs.map(l => NetworkApi.route(l.route).catch(() => null))).then(details =>
      setLines(details.flatMap((d, i) => (d?.directions?.[0]?.geometry?.length ? [{ coords: d.directions[0].geometry!, color: LEG_COLORS[i % 3] }] : [])))
    );
  }, [result, picked]);

  return (
    <FeatureShell
      title={a('tileFare')}
      icon="calculator-outline"
      color={OLIVE}
      renderMap={mapType => <NetworkMap vehicles={[]} selectedVehicleId={null} mapType={mapType} routeLines={lines} />}
    >
      <OriginDestination from={from} to={to} setFrom={setFrom} setTo={setTo} fromLabel={a('fsEnterOrigin')} toLabel={a('fsEnterDestination')} swapLabel={a('planSwap')} />
      <View style={{ height: 18 }} />
      <GradientButton label={busy ? a('fcCalculating') : a('fcGetRoute')} icon="calculator" onPress={() => calc()} busy={busy} disabled={from.trim().length < 2 || to.trim().length < 2} />

      {busy ? <View style={{ gap: 10, marginTop: 16 }}>{[0, 1].map(i => <Skeleton key={i} height={150} radius={16} />)}</View> : null}
      {error ? <Text style={styles.warn}>{error}</Text> : null}
      {result && !result.options.length ? <EmptyState compact title={a('fsNoJourney')} message={a('fcNone')} /> : null}

      {result?.options.map((o, i) => (
        <FadeIn key={i} delay={stagger(i, 80)}>
          <PressScale hoverLift={false} style={[styles.option, picked === i && styles.optionOn]} onPress={() => setPicked(i)} accessibilityRole="radio" accessibilityState={{ selected: picked === i }}>
            <View style={styles.routes}>
              {o.legs.map((l, li) => (
                <React.Fragment key={li}>
                  {li > 0 ? <Ionicons name="arrow-forward" size={14} color="#888" /> : null}
                  <Text style={[styles.badge, { backgroundColor: LEG_COLORS[li % 3] }]}>{l.route}</Text>
                </React.Fragment>
              ))}
              {o.minutes ? <Text style={styles.mins}>≈ {o.minutes} min</Text> : null}
            </View>
            <Text style={styles.trip} numberOfLines={2}>{o.legs[0].from} → {o.legs[o.legs.length - 1].to}</Text>
            <Text style={styles.dist}>
              {o.legs.map(l => (l.distance_km != null ? `${l.distance_km} km${l.stage ? ` · ${a('fcStage', { n: l.stage })}` : ''}` : '—')).join('  +  ')}
            </Text>
            <View style={styles.cats}>
              {CATS.map(([k, label, c]) => (
                <View key={k} style={[styles.cat, { borderColor: c }]}>
                  <Text style={[styles.catLabel, { color: c }]}>{a(label)}</Text>
                  <Text style={styles.catAmount}>₹{o.totals[k]}</Text>
                </View>
              ))}
            </View>
            {o.legs.length > 1 ? <Text style={styles.small}>{a('fcPerBus', { n: o.legs.length })}</Text> : null}
            {o.estimate ? <Text style={styles.estimate}>{a('fcEstimate')}</Text> : null}
            {picked === i ? (
              <PressScale hoverLift={false} style={styles.buy} onPress={() => router.push({ pathname: '/access/buy', params: { route: o.legs[0].route } } as any)} accessibilityRole="button">
                <Ionicons name="ticket-outline" size={16} color="#B1285F" /><Text style={styles.buyText}>{a('planBuy')}</Text>
              </PressScale>
            ) : null}
          </PressScale>
        </FadeIn>
      ))}
      {result?.options.length ? <Text style={styles.note}>{a('fcNote')}</Text> : null}

      {!result && !busy ? (
        <RecentList title={a('fsRecent')} items={recent.items.map(r => ({ key: r.key, label: `${r.from} → ${r.to}` }))} icon="calculator-outline"
          onClear={recent.clear} clearLabel={a('fsClear')}
          onPick={k => { const r = recent.items.find(x => x.key === k); if (r) { setFrom(r.from); setTo(r.to); calc(r.from, r.to); } }} />
      ) : null}
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  option: { backgroundColor: '#FFFFFF', borderRadius: 16, padding: 14, marginTop: 14, borderWidth: 1, borderColor: '#E3E5EA' },
  optionOn: { borderColor: OLIVE, borderWidth: 2, backgroundColor: '#FAFBF2' },
  routes: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  badge: { color: '#FFFFFF', fontWeight: '900', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, overflow: 'hidden' },
  mins: { marginLeft: 'auto', color: '#666', fontWeight: '700' },
  trip: { color: '#1E1E24', marginTop: 6 },
  dist: { color: '#666', fontSize: 12, marginTop: 2 },
  cats: { flexDirection: 'row', gap: 8, marginTop: 10 },
  cat: { flex: 1, borderWidth: 1.5, borderRadius: 12, paddingVertical: 8, alignItems: 'center' },
  catLabel: { fontSize: 12, fontWeight: '800' },
  catAmount: { fontSize: 21, fontWeight: '900', color: '#1E1E24', marginTop: 2 },
  small: { color: '#666', fontSize: 12, marginTop: 6 },
  estimate: { color: '#7A4B00', fontSize: 12, fontWeight: '700', marginTop: 6 },
  buy: { flexDirection: 'row', gap: 6, marginTop: 10, minHeight: 42, borderRadius: 12, borderWidth: 1.5, borderColor: '#B1285F', alignItems: 'center', justifyContent: 'center' },
  buyText: { color: '#B1285F', fontWeight: '800' },
  note: { color: '#777', fontSize: 12, marginTop: 14, lineHeight: 17 },
  warn: { color: '#8E1C1C', marginTop: 14 },
});
