import React, { useCallback } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../constants/theme';
import { AccessKey, useAccessT } from '../constants/accessI18n';
import { AuthButton, AuthScreen } from '../components/auth/AuthUi';
import { Loading } from '../components/access/AccessUi';
import { FadeIn, stagger } from '../components/ui/motion';
import { useNotifications } from '../hooks/useNotifications';
import type { AccessNotification } from '../services/accessApi';

const ICON: Record<string, { icon: keyof typeof Ionicons.glyphMap; color: string }> = {
  TICKET_ISSUED: { icon: 'ticket-outline', color: '#0F7A3A' },
  PASS_APPROVED: { icon: 'school-outline', color: '#0F7A3A' },
  PASS_REJECTED: { icon: 'close-circle-outline', color: '#B3141B' },
  PASS_REVOKED: { icon: 'close-circle-outline', color: '#B3141B' },
  PASS_EXPIRING: { icon: 'time-outline', color: '#9A5A00' },
  BUS_FULL: { icon: 'people', color: '#B3141B' },
  BUS_NEARLY_FULL: { icon: 'people-outline', color: '#9A5A00' },
  COLLEGE_QUEUE: { icon: 'documents-outline', color: COLORS.primary },
  PAYMENT_REFUNDED: { icon: 'cash-outline', color: '#9A5A00' },
};

/** In-app notifications from the backend (ticket issued, bus pass decisions, bus full, …). */
export default function NotificationsScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const { ready, signedIn, items, unread, loaded, refresh, markAllRead } = useNotifications();
  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));

  const text = (n: AccessNotification, part: 't' | 'b') => {
    const key = `n${n.kind}_${part}` as AccessKey;
    const out = a(key, n.data as any);
    return out === key ? (part === 't' ? n.title : n.body) : out;
  };
  const open = (n: AccessNotification) => {
    if (n.data?.ticket_id && n.kind === 'TICKET_ISSUED') router.push({ pathname: '/access/ticket', params: { id: n.data.ticket_id } } as any);
    else if (n.kind.startsWith('PASS_')) router.push('/access/student' as any);
    else if (n.kind.startsWith('BUS_')) router.push('/access/conductor' as any);
    else if (n.kind === 'COLLEGE_QUEUE') router.push('/access/college' as any);
  };

  return (
    <AuthScreen title={a('notifTitle')}>
      {!ready || (signedIn && !loaded) ? <Loading /> : null}
      {ready && !signedIn ? (
        <>
          <Text style={styles.empty}>{a('notifSignIn')}</Text>
          <AuthButton label={a('signIn')} onPress={() => router.push('/access' as any)} />
        </>
      ) : null}
      {signedIn && loaded && items.length === 0 ? (
        <View style={styles.emptyBox}>
          <Ionicons name="notifications-off-outline" size={36} color={COLORS.textMuted} />
          <Text style={styles.empty}>{a('notifEmpty')}</Text>
        </View>
      ) : null}
      {unread ? <AuthButton variant="link" icon="checkmark-done-outline" label={a('notifMarkAll')} onPress={markAllRead} /> : null}
      <ScrollView refreshControl={<RefreshControl refreshing={false} onRefresh={refresh} />} contentContainerStyle={{ gap: SPACING.sm }}>
        {items.map((n, i) => {
          const m = ICON[n.kind] || { icon: 'notifications-outline' as const, color: COLORS.primary };
          return (
            <FadeIn key={n.id} delay={stagger(i)}>
              <TouchableOpacity style={[styles.item, !n.read && styles.unread]} onPress={() => open(n)} accessibilityRole="button"
                accessibilityLabel={`${text(n, 't')}. ${text(n, 'b')}`}>
                <View style={[styles.icon, { backgroundColor: `${m.color}1A` }]}>
                  <Ionicons name={m.icon} size={20} color={m.color} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>{text(n, 't')}</Text>
                  <Text style={styles.body}>{text(n, 'b')}</Text>
                  {n.created_at ? <Text style={styles.time}>{new Date(n.created_at).toLocaleString()}</Text> : null}
                </View>
                {!n.read ? <View style={styles.dot} /> : null}
              </TouchableOpacity>
            </FadeIn>
          );
        })}
      </ScrollView>
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  emptyBox: { alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.xl },
  empty: { color: COLORS.textSecondary, fontSize: 15, textAlign: 'center', marginVertical: SPACING.md },
  item: { flexDirection: 'row', gap: SPACING.md, alignItems: 'flex-start', backgroundColor: '#FFFFFF', borderRadius: RADIUS.lg,
    padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border, minHeight: 64 },
  unread: { borderColor: COLORS.primary, backgroundColor: '#F6FAFF' },
  icon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 15, fontWeight: '800', color: COLORS.textPrimary },
  body: { fontSize: 14, color: COLORS.textSecondary, marginTop: 2 },
  time: { fontSize: 12, color: COLORS.textMuted, marginTop: 4 },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: COLORS.primary, marginTop: 6 },
});
