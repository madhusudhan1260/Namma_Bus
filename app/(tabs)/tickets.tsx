import React, { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useAccessSession } from '../../components/access/AccessAccountCard';
import { Loading, OfflineBanner, StatusBadge } from '../../components/access/AccessUi';
import { FadeIn, PressScale, stagger } from '../../components/ui/motion';
import { AccessApi } from '../../services/accessApi';

/** Display status: an issued ticket past its validity is shown as expired; refunds as refunded. */
function statusOf(t: any): string {
  if (t.payment_status === 'REFUNDED') return 'REFUNDED';
  if (t.status === 'ISSUED' && new Date(t.expires_at).getTime() <= Date.now()) return 'EXPIRED';
  return t.status;
}

const PILL: Record<string, { bg: string; fg: string }> = {
  ISSUED: { bg: '#E3F6EA', fg: '#0F7A3A' }, PENDING_PAYMENT: { bg: '#FFF2DB', fg: '#9A5A00' }, USED: { bg: '#EEF0F4', fg: '#44506A' },
  CANCELLED: { bg: '#FDE8E8', fg: '#8E1C1C' }, REFUNDED: { bg: '#FFF2DB', fg: '#9A5A00' }, REVOKED: { bg: '#FDE8E8', fg: '#8E1C1C' },
  EXPIRED: { bg: '#EEF0F4', fg: '#44506A' },
};

type GroupKey = 'jToday' | 'jYesterday' | 'jThisWeek' | 'jEarlier';

/** Today / Yesterday / This week (last 7 days) / Earlier, by the device's local date. */
function groupByDay(list: any[]): { key: GroupKey; items: any[] }[] {
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = startOf(new Date());
  const day = 86400000;
  const out: Record<GroupKey, any[]> = { jToday: [], jYesterday: [], jThisWeek: [], jEarlier: [] };
  for (const t of list) {
    const d = startOf(new Date(t.issued_at || t.created_at));
    const key: GroupKey = d >= today ? 'jToday' : d >= today - day ? 'jYesterday' : d >= today - 6 * day ? 'jThisWeek' : 'jEarlier';
    out[key].push(t);
  }
  return (Object.keys(out) as GroupKey[]).filter(k => out[k].length).map(k => ({ key: k, items: out[k] }));
}

/** Tickets tab — My journeys: active tickets first, then history grouped by day. Server-issued; available offline. */
export default function TicketsTab() {
  const router = useRouter();
  const { a } = useAccessT();
  const session = useAccessSession();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const traveller = !!session && ['PASSENGER', 'STUDENT'].includes(session.role);

  const load = useCallback(() => {
    if (!traveller) return;
    AccessApi.tickets().then(r => { setData(r); setError(null); }).catch(e => setError(e.message));
  }, [traveller]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const tickets: any[] = data?.tickets || [];
  const isActive = (t: any) => (t.status === 'ISSUED' && new Date(t.expires_at).getTime() > Date.now()) || t.status === 'PENDING_PAYMENT';
  const active = tickets.filter(isActive);
  const groups = groupByDay(tickets.filter(t => !isActive(t)));
  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = async () => {
    setRefreshing(true);
    try {
      setData(await AccessApi.tickets());
    } catch {
      /* keep the cached list */
    } finally {
      setRefreshing(false);
    }
  };

  const card = (t: any, ti: number) => {
    const st = statusOf(t);
    return (
      <FadeIn key={t.ticket_id} delay={stagger(ti, 55)}>
        <PressScale style={[styles.card, st === 'ISSUED' && styles.cardValid]}
          onPress={() => router.push({ pathname: '/access/ticket', params: { id: t.ticket_id } } as any)}
          accessibilityRole="button" accessibilityLabel={`${t.route} ${t.from_stop} ${t.to_stop} ₹${t.fare} ${a(('st' + st) as any)}`}>
          <View style={styles.row}>
            <Text style={styles.route}>{t.route}</Text>
            <Text style={styles.fare}>{t.fare === 0 ? a('jFree') : `₹${t.fare}`}</Text>
          </View>
          <Text style={styles.stops} numberOfLines={1}>{t.from_stop} → {t.to_stop}</Text>
          <View style={styles.row}>
            <Text style={styles.meta}>
              {new Date(t.issued_at || t.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} · {new Date(t.issued_at || t.created_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
              {' · '}{t.fare === 0 ? a('jFree') : a('jPaid')}{t.trip?.trip_code ? ` · ${t.trip.trip_code}` : ''}
            </Text>
            <View style={[styles.pill, { backgroundColor: PILL[st]?.bg || '#EEF0F4' }]}>
              <Text style={[styles.pillText, { color: PILL[st]?.fg || '#44506A' }]}>{a(('st' + st) as any)}</Text>
            </View>
          </View>
        </PressScale>
      </FadeIn>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">{a('myJourneys')}</Text>
        <TouchableOpacity style={styles.buy} onPress={() => router.push('/access/buy' as any)} accessibilityRole="button">
          <Ionicons name="add" size={18} color={COLORS.textInverse} />
          <Text style={styles.buyText}>{a('quickBuy')}</Text>
        </TouchableOpacity>
      </View>
      <ScrollView contentContainerStyle={styles.list} refreshControl={traveller ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}>
        {session === undefined ? <Loading lines={2} /> : null}
        {session !== undefined && !traveller ? (
          <View style={styles.empty}>
            <Ionicons name="ticket-outline" size={40} color={COLORS.textMuted} />
            <Text style={styles.emptyText}>{a('signInToSee')}</Text>
            <TouchableOpacity style={styles.signIn} onPress={() => router.push({ pathname: '/access', params: { next: '/tickets' } } as any)} accessibilityRole="button">
              <Text style={styles.buyText}>{a('signIn')}</Text>
            </TouchableOpacity>
          </View>
        ) : null}
        {traveller && data?.offline ? <OfflineBanner at={data.cached_at} /> : null}
        {traveller && error && !data ? <Text style={styles.error}>{error}</Text> : null}
        {traveller && !data && !error ? <Loading /> : null}
        {traveller && data && tickets.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="ticket-outline" size={40} color={COLORS.textMuted} />
            <Text style={styles.emptyText}>{a('noTickets')}</Text>
          </View>
        ) : null}
        {active.length ? <Text style={styles.group}>{a('jActive')}</Text> : null}
        {active.map(card)}
        {groups.map(g => (
          <View key={g.key}>
            <Text style={styles.group}>{a(g.key)}</Text>
            {g.items.map(card)}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface },
  title: { fontSize: 20, fontWeight: '900', color: COLORS.deepNavy },
  buy: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 40, paddingHorizontal: 14, borderRadius: RADIUS.full, backgroundColor: COLORS.deepNavy },
  buyText: { color: COLORS.textInverse, fontWeight: '800' },
  list: { padding: SPACING.md, width: '100%', maxWidth: 760, alignSelf: 'center' },
  empty: { alignItems: 'center', paddingVertical: SPACING.xxl, gap: SPACING.sm },
  emptyText: { color: COLORS.textSecondary, fontSize: 15 },
  signIn: { minHeight: 44, paddingHorizontal: 20, borderRadius: RADIUS.md, backgroundColor: COLORS.deepNavy, justifyContent: 'center' },
  error: { color: '#8E1C1C', marginBottom: SPACING.md },
  card: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.md, marginBottom: SPACING.sm },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: SPACING.sm },
  route: { fontSize: 18, fontWeight: '900', color: COLORS.deepNavy },
  fare: { fontSize: 18, fontWeight: '900', color: COLORS.textPrimary },
  stops: { color: COLORS.textPrimary, marginVertical: 4 },
  meta: { color: COLORS.textSecondary, fontSize: 12, flexShrink: 1 },
  status: { fontSize: 12, fontWeight: '800', color: COLORS.textSecondary },
  cardValid: { borderColor: '#1FA855', borderWidth: 2 },
  group: { fontSize: 13, fontWeight: '900', color: COLORS.textSecondary, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: SPACING.md, marginBottom: SPACING.sm },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { fontSize: 12, fontWeight: '900' },
});
