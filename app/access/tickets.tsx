import React, { useCallback, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { COLORS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen } from '../../components/auth/AuthUi';
import { Card, ErrorText, Loading, OfflineBanner, useAccessGuard } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';

export default function MyTickets() {
  const router = useRouter();
  const { a } = useAccessT();
  const { ready } = useAccessGuard(['PASSENGER', 'STUDENT']);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    AccessApi.tickets().then(r => { setData(r); setError(null); }).catch(e => setError(e.message));
  }, []);
  useFocusEffect(useCallback(() => { if (ready) load(); }, [ready, load]));

  const tickets: any[] | null = data?.tickets ?? null;
  return (
    <AuthScreen
      title={a('myTicketsTitle')}
      footer={<AuthButton icon="ticket-outline" label={a('buyTicket')} onPress={() => router.push('/access/buy' as any)} />}
    >
      {data?.offline ? <OfflineBanner at={data.cached_at} /> : null}
      <ErrorText text={error} />
      {error && !tickets ? <AuthButton variant="secondary" label={a('tryAgain')} onPress={load} /> : null}
      {!tickets && !error ? <Loading /> : null}
      {tickets && tickets.length === 0 ? <Text style={styles.empty}>{a('noTickets')}</Text> : null}
      {tickets?.map(t => (
        <TouchableOpacity key={t.ticket_id} onPress={() => router.push({ pathname: '/access/ticket', params: { id: t.ticket_id } } as any)}
          accessibilityRole="button" accessibilityLabel={`${t.route} ${t.from_stop} ${t.to_stop} ₹${t.fare} ${t.status}`}>
          <Card>
            <View style={styles.row}>
              <Text style={styles.route}>{t.route}</Text>
              <Text style={styles.fare}>₹{t.fare}</Text>
            </View>
            <Text style={styles.stops} numberOfLines={1}>{t.from_stop} → {t.to_stop}</Text>
            <Text style={styles.meta}>
              {t.reference} · {t.ticket_type === 'ELIGIBLE_FREE' ? `${a('eligible')} (${t.eligibility_type})` : a('paid')} · {t.status} · {new Date(t.created_at).toLocaleString()}
            </Text>
          </Card>
        </TouchableOpacity>
      ))}
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  empty: { color: COLORS.textSecondary, marginBottom: SPACING.md },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  route: { fontSize: 18, fontWeight: '900', color: COLORS.deepNavy },
  fare: { fontSize: 18, fontWeight: '900', color: COLORS.textPrimary },
  stops: { color: COLORS.textPrimary, marginTop: 4 },
  meta: { color: COLORS.textSecondary, fontSize: 12, marginTop: 4 },
});
