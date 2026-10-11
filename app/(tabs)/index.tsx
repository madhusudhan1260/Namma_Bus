import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useTransit } from '../../context/TransitContext';
import { NearbyLiveBuses } from '../../components/network/NearbyLiveBuses';
import { useAccessSession } from '../../components/access/AccessAccountCard';
import { CITY_CENTRE, Coords, positionIfGranted } from '../../components/access/location';
import { AccessApi, RecentJourney } from '../../services/accessApi';
import { NetworkApi } from '../../services/networkApi';
import { NetworkJourneyPlan } from '../../types/network';
import { FadeIn, PressScale, Skeleton, stagger } from '../../components/ui/motion';
import { HeroScene } from '../../components/home/HeroScene';
import { FeatureTile } from '../../components/home/FeatureTile';
import { NotificationBell } from '../../components/access/NotificationBell';

/**
 * Home — real data only: journey planning on the BMTC GTFS network, nearby live buses and stops from
 * the BMTC feed / network, and the user's own recent journeys. No simulated buses, alerts or predictions.
 */
export default function HomeScreen() {
  const router = useRouter();
  const { a, lang } = useAccessT();
  const { setPreferredLanguage } = useTransit();
  const session = useAccessSession();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [plans, setPlans] = useState<NetworkJourneyPlan[] | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentJourney[]>([]);
  const [pos, setPos] = useState<Coords | null>(null);
  const [stops, setStops] = useState<any[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    if (!session) return setName(null);
    AccessApi.me().then((m: any) => setName((m?.name || '').split(' ')[0] || null)).catch(() => setName(null));
  }, [session?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const { width, height } = useWindowDimensions();
  const heroHeight = Math.round(Math.min(520, Math.max(330, height * 0.52, width * 0.36)));
  // Even tile grid: 4 per row when there is room, 2 per row on phones; every tile the same width
  const gridWidth = Math.min(width, 1240) - 32;
  const cols = gridWidth >= 640 ? 4 : 2;
  const gap = cols === 4 ? 18 : 12;
  const tileWidth = Math.floor((gridWidth - gap * (cols - 1)) / cols);
  const compactTiles = cols === 2 || tileWidth < 170;
  const narrowCta = width < 520;
  const scrollRef = useRef<ScrollView>(null);
  const fromRef = useRef<TextInput>(null);
  const [plannerY, setPlannerY] = useState(0);
  const goToPlanner = () => {
    scrollRef.current?.scrollTo({ y: Math.max(0, plannerY - 12), animated: true });
    setTimeout(() => fromRef.current?.focus(), 450);
  };

  const hour = new Date().getHours();
  const greeting = hour < 12 ? a('homeGreetingMorning') : hour < 17 ? a('homeGreetingAfternoon') : a('homeGreetingEvening');

  useFocusEffect(
    useCallback(() => {
      AccessApi.recentJourneys().then(setRecent).catch(() => setRecent([]));
    }, [session?.user_id])
  );

  useEffect(() => {
    positionIfGranted().then(setPos);
  }, []);

  useEffect(() => {
    const o = pos || CITY_CENTRE;
    NetworkApi.stopsNearby(o.latitude, o.longitude, 700, 6)
      .then(r => setStops(r.stops))
      .catch(() => setStops([]));
  }, [pos]);

  const plan = async () => {
    if (from.trim().length < 2 || to.trim().length < 2) return;
    setPlanning(true);
    setPlanError(null);
    try {
      const r = await NetworkApi.journey(from.trim(), to.trim());
      setPlans(r.plans);
    } catch (e: any) {
      setPlans(null);
      setPlanError(e.message);
    } finally {
      setPlanning(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView ref={scrollRef} style={styles.scrollBg} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <HeroScene
          height={heroHeight}
          subtitle={a('heroSubtitle')}
          topRight={
            <>
              <TouchableOpacity style={styles.heroPill} onPress={() => router.push('/emergency' as any)} accessibilityRole="button" accessibilityLabel={a('fsHelpline')}>
                <Ionicons name="call-outline" size={15} color={COLORS.deepNavy} />
                <Text style={styles.heroPillText}>{a('fsHelpline')}</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.heroPill} onPress={() => setPreferredLanguage(lang === 'EN' ? 'KN' : 'EN')} accessibilityRole="button" accessibilityLabel={a('language')}>
                <Ionicons name="language-outline" size={15} color={COLORS.deepNavy} />
                <Text style={styles.heroPillText}>{lang === 'EN' ? 'ಕನ್ನಡ' : 'English'}</Text>
              </TouchableOpacity>
              <NotificationBell />
              <TouchableOpacity style={styles.heroPill} onPress={() => router.push((session ? '/(tabs)/more' : '/access') as any)} accessibilityRole="button" accessibilityLabel={session ? a('moreTitle') : a('signIn')}>
                <Ionicons name={session ? 'person-circle-outline' : 'log-in-outline'} size={17} color={COLORS.deepNavy} />
                {!session ? <Text style={styles.heroPillText}>{a('signIn')}</Text> : null}
              </TouchableOpacity>
            </>
          }
        />

        {/* Feature tiles (overlap the bottom of the hero) */}
        <View style={[styles.tiles, { gap, width: gridWidth + 32, marginTop: compactTiles ? -48 : -64 }]}>
          <FeatureTile index={0} width={tileWidth} compact={compactTiles} icon="navigate-outline" color="#F7B21B" label={a('tileJourney')} onPress={() => router.push('/planner' as any)} />
          <FeatureTile index={1} width={tileWidth} compact={compactTiles} icon="bus-outline" color="#EF7D12" label={a('tileLiveBuses')} onPress={() => router.push('/track-bus' as any)} />
          <FeatureTile index={2} width={tileWidth} compact={compactTiles} icon="time-outline" color="#1FBF7F" label={a('tileTimetable')} onPress={() => router.push('/timetable' as any)} />
          <FeatureTile index={3} width={tileWidth} compact={compactTiles} icon="calculator-outline" color="#9AA23A" label={a('tileFare')} onPress={() => router.push('/fare' as any)} />
          <FeatureTile index={4} width={tileWidth} compact={compactTiles} icon="business-outline" color="#F0506E" label={a('tileFacilities')} onPress={() => router.push('/facilities' as any)} />
          <FeatureTile index={5} width={tileWidth} compact={compactTiles} icon="alert-circle-outline" color="#E11D48" label={a('tileEmergency')} onPress={() => router.push('/emergency' as any)} />
          <FeatureTile index={6} width={tileWidth} compact={compactTiles} icon="document-text-outline" color="#7C3AED" label={a('tileComplaint')} onPress={() => router.push('/complaint' as any)} />
          <FeatureTile index={7} width={tileWidth} compact={compactTiles} icon="sparkles-outline" color="#2E8BF0" label={a('tileAi')} onPress={() => router.push('/(tabs)/ai' as any)} />
        </View>

        <View style={styles.inner}>
          <FadeIn delay={420}>
            <Text style={styles.hello} accessibilityRole="header">{name ? a('homeGreetName', { greeting, name }) : greeting}</Text>
            <Text style={styles.tagline}>{a('heroTagline')}</Text>
          </FadeIn>
          <FadeIn delay={500} style={styles.ctaRow}>
            <PressScale style={[styles.cta, narrowCta && styles.ctaNarrow, { backgroundColor: '#C2185B' }]} onPress={goToPlanner} accessibilityRole="button" accessibilityLabel={a('ctaPlan')}>
              <Ionicons name="navigate-outline" size={20} color="#FFFFFF" />
              <Text style={[styles.ctaText, narrowCta && styles.ctaTextNarrow]}>{a('ctaPlan')}</Text>
            </PressScale>
            <PressScale style={[styles.cta, narrowCta && styles.ctaNarrow, { backgroundColor: '#EF7D12' }]} onPress={() => router.push('/track-bus' as any)} accessibilityRole="button" accessibilityLabel={a('ctaTrack')}>
              <Ionicons name="bus-outline" size={20} color="#FFFFFF" />
              <Text style={[styles.ctaText, narrowCta && styles.ctaTextNarrow]}>{a('ctaTrack')}</Text>
            </PressScale>
            <PressScale style={[styles.cta, narrowCta && styles.ctaNarrow, { backgroundColor: COLORS.deepNavy }]} onPress={() => router.push('/access/buy' as any)} accessibilityRole="button" accessibilityLabel={a('ctaBuy')}>
              <Ionicons name="ticket-outline" size={20} color="#FFFFFF" />
              <Text style={[styles.ctaText, narrowCta && styles.ctaTextNarrow]}>{a('ctaBuy')}</Text>
            </PressScale>
          </FadeIn>
        </View>

        {/* Real nearby buses (BMTC feed) */}
        <View style={styles.innerFlush}>
          <NearbyLiveBuses />
        </View>

        <View style={styles.inner}>
          <View onLayout={e => setPlannerY(e.nativeEvent.layout.y)}>
            <Text style={styles.title} accessibilityRole="header">{a('homeWhereTo')}</Text>
          </View>

          {/* Journey planner (real BMTC network) */}
          <FadeIn delay={120} style={styles.card}>
            <View style={styles.inputRow}>
              <Ionicons name="radio-button-on" size={16} color={COLORS.primary} />
              <TextInput ref={fromRef} style={styles.input} value={from} onChangeText={setFrom} placeholder={a('planFrom')} placeholderTextColor={COLORS.textMuted} accessibilityLabel={a('planFrom')} />
            </View>
            <View style={styles.inputRow}>
              <Ionicons name="location" size={16} color="#C0392B" />
              <TextInput style={styles.input} value={to} onChangeText={setTo} placeholder={a('planTo')} placeholderTextColor={COLORS.textMuted} accessibilityLabel={a('planTo')}
                onSubmitEditing={plan} returnKeyType="search" />
              <TouchableOpacity onPress={() => { setFrom(to); setTo(from); }} accessibilityRole="button" accessibilityLabel={a('planSwap')} style={styles.swap}>
                <Ionicons name="swap-vertical" size={20} color={COLORS.deepNavy} />
              </TouchableOpacity>
            </View>
            <TouchableOpacity style={[styles.primary, (from.trim().length < 2 || to.trim().length < 2) && { opacity: 0.5 }]} onPress={plan}
              disabled={planning || from.trim().length < 2 || to.trim().length < 2} accessibilityRole="button">
              {planning ? <ActivityIndicator color={COLORS.textInverse} /> : <Text style={styles.primaryText}>{a('planFind')}</Text>}
            </TouchableOpacity>
            {planError ? <Text style={styles.error}>{planError}</Text> : null}
            {plans && plans.length === 0 ? <Text style={styles.muted}>{a('planNone')}</Text> : null}
            {plans && plans.length > 0 ? (
              <View style={{ marginTop: SPACING.md }}>
                <Text style={styles.section}>{a('planResults')}</Text>
                {plans.slice(0, 5).map((p, pi) => (
                  <FadeIn key={p.id} delay={stagger(pi, 60)} style={styles.plan}>
                    <View style={styles.planRoutes}>
                      {p.legs.map((l, i) => (
                        <React.Fragment key={`${p.id}-${i}`}>
                          {i > 0 ? <Ionicons name="arrow-forward" size={14} color={COLORS.textMuted} /> : null}
                          <Text style={styles.badge}>{l.routeNumber}</Text>
                        </React.Fragment>
                      ))}
                    </View>
                    <Text style={styles.planText} numberOfLines={2}>
                      {p.legs[0]?.fromStop.name} → {p.legs[p.legs.length - 1]?.toStop.name}
                    </Text>
                    <Text style={styles.planMeta}>
                      {a('planStops', { n: p.legs.reduce((s, l) => s + (l.stopCount || 0), 0) })} · {a('planMinutes', { n: p.totalDurationMinutes })}
                      {p.transferCount ? ` · ${a('planChange')}` : ''}
                    </Text>
                    <View style={styles.planActions}>
                      <TouchableOpacity style={styles.secondary} onPress={() => router.push({ pathname: '/network/route/[route]', params: { route: p.legs[0].routeNumber } } as any)} accessibilityRole="button">
                        <Text style={styles.secondaryText}>{a('planViewRoute')}</Text>
                      </TouchableOpacity>
                      <TouchableOpacity style={styles.secondary} onPress={() => router.push({ pathname: '/access/buy', params: { route: p.legs[0].routeNumber } } as any)} accessibilityRole="button">
                        <Text style={styles.secondaryText}>{a('planBuy')}</Text>
                      </TouchableOpacity>
                    </View>
                  </FadeIn>
                ))}
                <Text style={styles.small}>{a('planScheduled')}</Text>
              </View>
            ) : null}
          </FadeIn>


          {recent.length ? (
            <FadeIn delay={260} style={styles.block}>
              <Text style={styles.section}>{a('recentTitle')}</Text>
              {recent.map((r, ri) => (
                <FadeIn key={`${r.route}-${r.from_stop_id}-${r.to_stop_id}`} delay={300 + stagger(ri)}>
                  <PressScale style={styles.row} hoverLift={false}
                    onPress={() => router.push({ pathname: '/access/buy', params: { route: r.route, direction: String(r.direction) } } as any)} accessibilityRole="button">
                    <Text style={styles.badge}>{r.route}</Text>
                    <Text style={styles.rowText} numberOfLines={1}>{r.from_stop} → {r.to_stop}</Text>
                    <Ionicons name="chevron-forward" size={16} color={COLORS.textMuted} />
                  </PressScale>
                </FadeIn>
              ))}
            </FadeIn>
          ) : null}
        </View>

        <View style={styles.inner}>
          <View style={styles.block}>
            <Text style={styles.section}>{a('nearbyStopsTitle')}</Text>
            {stops === null
              ? [0, 1, 2].map(i => (
                  <View key={i} style={[styles.row, { gap: 12 }]}>
                    <Skeleton width={18} height={18} radius={9} />
                    <Skeleton width="55%" height={13} />
                  </View>
                ))
              : null}
            {stops && stops.length === 0 ? <Text style={styles.muted}>{a('nearbyStopsNone', { m: 700 })}</Text> : null}
            {stops?.map((s, i) => (
              <FadeIn key={`${s.id}-${i}`} delay={stagger(i)}>
                <PressScale style={styles.row} hoverLift={false} onPress={() => setFrom(s.name)} accessibilityRole="button" accessibilityHint={a('useAsFrom')}>
                  <Text style={{ fontSize: 16 }}>🚏</Text>
                  <Text style={styles.rowText} numberOfLines={1}>{s.name}</Text>
                  {s.distance != null || s.distanceMeters != null ? <Text style={styles.planMeta}>{Math.round(s.distance ?? s.distanceMeters)} m</Text> : null}
                </PressScale>
              </FadeIn>
            ))}
          </View>
          <Text style={styles.footer}>{a('dataSourceNote')}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}


const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#E4566E' },
  scrollBg: { backgroundColor: COLORS.background },
  scroll: { paddingBottom: SPACING.xxxl },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-start', paddingHorizontal: 16, marginBottom: SPACING.lg, alignSelf: 'center' },
  heroPill: {
    flexDirection: 'row', alignItems: 'center', gap: 5, minHeight: 40, paddingHorizontal: 14, borderRadius: 12, backgroundColor: '#FFFFFF',
    shadowColor: '#3B0A24', shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 3 },
  },
  heroPillText: { fontWeight: '800', color: COLORS.deepNavy, fontSize: 13 },
  ctaRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.lg },
  cta: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 54, borderRadius: 16 },
  ctaText: { color: '#FFFFFF', fontWeight: '900', fontSize: 15 },
  inner: { paddingHorizontal: SPACING.md, width: '100%', maxWidth: 760, alignSelf: 'center' },
  innerFlush: { width: '100%', maxWidth: 760 + 2 * 16, alignSelf: 'center' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: SPACING.sm },
  brand: { fontSize: 20, fontWeight: '900', color: COLORS.deepNavy, letterSpacing: 0.5 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  brandMark: { width: 32, height: 32, borderRadius: 10, backgroundColor: COLORS.deepNavy, alignItems: 'center', justifyContent: 'center' },
  hero: { flexDirection: 'row', alignItems: 'flex-end', marginBottom: SPACING.sm, minHeight: 84 },
  heroBus: { marginLeft: SPACING.sm, marginBottom: SPACING.md, opacity: 0.95 },
  quickIcon: { width: 40, height: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  headerActions: { flexDirection: 'row', gap: SPACING.sm },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 40, paddingHorizontal: 12, borderRadius: RADIUS.full, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  pillText: { fontWeight: '700', color: COLORS.deepNavy, fontSize: 13 },
  greeting: { fontSize: 14, color: COLORS.textSecondary, marginTop: SPACING.sm },
  hello: { fontSize: 24, fontWeight: '900', color: COLORS.deepNavy, marginTop: SPACING.md },
  tagline: { fontSize: 15, color: COLORS.textSecondary, marginTop: 2, marginBottom: SPACING.md },
  ctaNarrow: { flexDirection: 'column', gap: 4, minHeight: 68, paddingHorizontal: 4 },
  ctaTextNarrow: { fontSize: 13, textAlign: 'center' },
  title: { fontSize: 24, fontWeight: '900', color: COLORS.textPrimary, marginBottom: SPACING.md },
  card: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.md, marginBottom: SPACING.md },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle, minHeight: 52 },
  input: { flex: 1, fontSize: 16, color: COLORS.textPrimary, minHeight: 48 },
  swap: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  primary: { marginTop: SPACING.md, minHeight: 50, borderRadius: RADIUS.md, backgroundColor: COLORS.deepNavy, alignItems: 'center', justifyContent: 'center' },
  primaryText: { color: COLORS.textInverse, fontWeight: '800', fontSize: 15 },
  secondary: { minHeight: 40, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.primary, justifyContent: 'center' },
  secondaryText: { color: COLORS.primaryDark, fontWeight: '700' },
  error: { color: '#8E1C1C', marginTop: SPACING.sm },
  muted: { color: COLORS.textSecondary, fontSize: 13, marginTop: SPACING.sm, lineHeight: 19 },
  small: { color: COLORS.textMuted, fontSize: 12, marginTop: SPACING.sm },
  section: { fontSize: 17, fontWeight: '800', color: COLORS.textPrimary, marginBottom: SPACING.sm },
  plan: { borderTopWidth: 1, borderTopColor: COLORS.borderSubtle, paddingVertical: SPACING.sm },
  planRoutes: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  planText: { color: COLORS.textPrimary, marginTop: 4 },
  planMeta: { color: COLORS.textSecondary, fontSize: 12, marginTop: 2 },
  planActions: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  badge: { backgroundColor: COLORS.deepNavy, color: COLORS.textInverse, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.sm, overflow: 'hidden', fontSize: 13 },
  quickRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.lg },
  quick: { flex: 1, minHeight: 72, borderRadius: RADIUS.lg, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center', gap: 4, paddingHorizontal: 4 },
  quickText: { fontSize: 12, fontWeight: '700', color: COLORS.textPrimary },
  block: { marginBottom: SPACING.lg },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, minHeight: 52, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  rowText: { flex: 1, color: COLORS.textPrimary },
  footer: { color: COLORS.textMuted, fontSize: 12, textAlign: 'center', marginTop: SPACING.md, lineHeight: 17 },
});
