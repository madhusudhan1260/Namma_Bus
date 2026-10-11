import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AccessApi, AccessSession, loadSession, onSessionChange } from '../../services/accessApi';
import { StatusBadge } from './AccessUi';

/** Tracks the signed-in ನಮ್ಮ Bus account (Access module). `undefined` while loading. */
export function useAccessSession() {
  const [s, setS] = useState<AccessSession | null | undefined>(undefined);
  useEffect(() => {
    loadSession().then(setS);
    const off = onSessionChange(setS);
    return () => {
      off();
    };
  }, []);
  return s;
}

/** Account card for the More tab: real account details, eligibility badges and account actions. */
export function AccessAccountCard({ fallback }: { fallback?: React.ReactNode }) {
  const router = useRouter();
  const { a } = useAccessT();
  const session = useAccessSession();
  const [me, setMe] = useState<any>(null);

  useFocusEffect(
    useCallback(() => {
      if (session && ['PASSENGER', 'STUDENT'].includes(session.role)) AccessApi.me().then(setMe).catch(() => undefined);
    }, [session])
  );

  if (session === undefined) return null;
  if (!session) {
    return (
      <View style={styles.card}>
        <TouchableOpacity style={styles.primary} onPress={() => router.push('/access' as any)} accessibilityRole="button">
          <Ionicons name="log-in-outline" size={18} color={COLORS.textInverse} style={{ marginRight: 8 }} />
          <Text style={styles.primaryText}>{a('login')} / {a('createAccount')}</Text>
        </TouchableOpacity>
        {fallback}
      </View>
    );
  }
  if (!['PASSENGER', 'STUDENT'].includes(session.role)) {
    const target = session.portal === 'conductor' ? '/access/conductor' : session.portal === 'college' ? '/access/college' : '/access/admin';
    return (
      <View style={styles.card}>
        <TouchableOpacity style={styles.primary} onPress={() => router.push(target as any)} accessibilityRole="button">
          <Ionicons name="briefcase-outline" size={18} color={COLORS.textInverse} style={{ marginRight: 8 }} />
          <Text style={styles.primaryText}>{session.portal.toUpperCase()}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const p = me?.passenger || {};
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(me?.name || '?').slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.name}>{me?.name || '…'}</Text>
          <Text style={styles.meta}>{me?.phone || me?.email || ''} · {session.role === 'STUDENT' ? a('roleStudent') : a('rolePassenger')}</Text>
        </View>
      </View>
      <View style={styles.badges}>
        {p.gender === 'FEMALE' ? <StatusBadge status={p.identity_status} /> : null}
        {me?.student ? <StatusBadge status={me.student.status} /> : null}
      </View>
      <Link icon="ticket-outline" label={a('myTickets')} onPress={() => router.push('/access/tickets' as any)} />
      <Link icon="person-circle-outline" label={a('yourEligibility')} onPress={() => router.push('/access/passenger' as any)} />
      {session.role === 'STUDENT' ? <Link icon="school-outline" label={a('studentVerification')} onPress={() => router.push('/access/student' as any)} /> : null}
      <Link icon="help-circle-outline" label={a('helpFeedback')} onPress={() => router.push('/access/help' as any)} />
      <Link icon="lock-closed-outline" label={a('privacyAccount')} onPress={() => router.push('/access/privacy' as any)} />
      <Link icon="log-out-outline" label={a('signOut')} onPress={() => AccessApi.logout()} />
    </View>
  );
}

function Link({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.link} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={18} color={COLORS.deepNavy} style={{ marginRight: 10 }} />
      <Text style={styles.linkText}>{label}</Text>
      <Ionicons name="chevron-forward" size={16} color={COLORS.textMuted} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.md },
  head: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, marginBottom: SPACING.sm },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: COLORS.deepNavy, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.textInverse, fontSize: 20, fontWeight: '900' },
  name: { fontSize: 17, fontWeight: '800', color: COLORS.textPrimary },
  meta: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  badges: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.sm, flexWrap: 'wrap' },
  link: { flexDirection: 'row', alignItems: 'center', minHeight: 48, borderTopWidth: 1, borderTopColor: COLORS.borderSubtle },
  linkText: { flex: 1, fontSize: 15, color: COLORS.textPrimary, fontWeight: '600' },
  primary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', minHeight: 48, borderRadius: RADIUS.md, backgroundColor: COLORS.deepNavy, marginBottom: SPACING.sm },
  primaryText: { color: COLORS.textInverse, fontWeight: '800' },
});
