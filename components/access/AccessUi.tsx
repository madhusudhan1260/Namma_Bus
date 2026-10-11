import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TextInput, TouchableOpacity, View, KeyboardTypeOptions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { FadeIn } from '../ui/motion';
import { useGlobalSearchParams, usePathname, useRouter } from 'expo-router';
import { AccessKey, useAccessT } from '../../constants/accessI18n';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { AccessApi, AccessRole, AccessSession, loadSession, onSessionChange } from '../../services/accessApi';

export const DEV_VERIFICATION_LABEL = 'DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION';

const BADGES: Record<string, { key: AccessKey; bg: string; fg: string }> = {
  VERIFIED: { key: 'badgeVERIFIED', bg: '#E3F6EA', fg: '#0F5F30' },
  APPROVED: { key: 'badgeVERIFIED', bg: '#E3F6EA', fg: '#0F5F30' },
  PENDING: { key: 'badgePENDING', bg: '#FFF4DB', fg: '#7A4B00' },
  REJECTED: { key: 'badgeREJECTED', bg: '#FDE8E8', fg: '#8E1C1C' },
  FAILED: { key: 'badgeFAILED', bg: '#FDE8E8', fg: '#8E1C1C' },
  EXPIRED: { key: 'badgeEXPIRED', bg: '#EEF0F4', fg: '#44506A' },
  DECLINED: { key: 'badgeNOT_VERIFIED', bg: '#EEF0F4', fg: '#44506A' },
  NOT_STARTED: { key: 'badgeNOT_VERIFIED', bg: '#EEF0F4', fg: '#44506A' },
  NOT_SUBMITTED: { key: 'badgeNOT_SUBMITTED', bg: '#EEF0F4', fg: '#44506A' },
  UNAVAILABLE: { key: 'badgeUNAVAILABLE', bg: '#EEF0F4', fg: '#44506A' },
};

/** Status badge: symbol + text (never colour alone), translated. */
export function StatusBadge({ status }: { status?: string | null }) {
  const { a } = useAccessT();
  const b = BADGES[status || 'NOT_STARTED'];
  const label = b ? a(b.key) : status || '—';
  return (
    <View style={[styles.badge, { backgroundColor: b?.bg || '#EEF0F4' }]} accessible accessibilityLabel={label}>
      <Text style={[styles.badgeText, { color: b?.fg || '#44506A' }]}>{label}</Text>
    </View>
  );
}

export function DevBanner({ text = DEV_VERIFICATION_LABEL }: { text?: string }) {
  return (
    <View style={styles.dev} accessibilityRole="alert">
      <Ionicons name="flask" size={16} color="#FFFFFF" style={{ marginRight: 6 }} />
      <Text style={styles.devText}>{text}</Text>
    </View>
  );
}

export function Card({ title, children, right }: { title?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <FadeIn style={styles.card}>
      {title ? (
        <View style={styles.cardHead}>
          <Text style={styles.cardTitle} accessibilityRole="header">{title}</Text>
          {right}
        </View>
      ) : null}
      {children}
    </FadeIn>
  );
}

export function Field(props: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  secure?: boolean;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: 'none' | 'words' | 'characters' | 'sentences';
  multiline?: boolean;
}) {
  const [focused, setFocused] = React.useState(false);
  return (
    <View style={{ marginBottom: SPACING.md }}>
      <Text style={styles.label}>{props.label}</Text>
      <TextInput
        style={[styles.input, props.multiline && { minHeight: 80, textAlignVertical: 'top' }, focused && styles.inputFocused]}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        value={props.value}
        onChangeText={props.onChangeText}
        placeholder={props.placeholder}
        placeholderTextColor={COLORS.textMuted}
        secureTextEntry={props.secure}
        keyboardType={props.keyboardType}
        autoCapitalize={props.autoCapitalize ?? 'none'}
        autoCorrect={false}
        multiline={props.multiline}
        accessibilityLabel={props.label}
      />
    </View>
  );
}

export function Choice({ options, value, onChange }: { options: { value: string; label: string }[]; value: string | null; onChange: (v: string) => void }) {
  return (
    <View style={styles.choiceRow}>
      {options.map(o => (
        <TouchableOpacity
          key={o.value}
          style={[styles.choice, value === o.value && styles.choiceActive]}
          onPress={() => onChange(o.value)}
          accessibilityRole="button"
          accessibilityState={{ selected: value === o.value }}
          accessibilityLabel={o.label}
        >
          <Text style={[styles.choiceText, value === o.value && styles.choiceTextActive]} numberOfLines={2}>{o.label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

export function Row({ label, value, bold }: { label: string; value?: React.ReactNode; bold?: boolean }) {
  return (
    <View style={styles.row} accessible>
      <Text style={styles.rowLabel}>{label}</Text>
      {typeof value === 'string' || typeof value === 'number' ? (
        <Text style={[styles.rowValue, bold && { fontSize: 18, fontWeight: '900' }]}>{value}</Text>
      ) : (
        value ?? <Text style={styles.rowValue}>—</Text>
      )}
    </View>
  );
}

export function Stat({ label, value }: { label: string; value: number | string | undefined }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value ?? '—'}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

export function ErrorText({ text }: { text?: string | null }) {
  return text ? <Text style={styles.error} accessibilityRole="alert">{text}</Text> : null;
}

/** Protects a portal screen: waits for the stored session and sends the user to sign-in (returning here afterwards). */
export function useAccessGuard(roles: AccessRole[]): { session: AccessSession | null; ready: boolean } {
  const router = useRouter();
  const pathname = usePathname();
  const search = useGlobalSearchParams();
  const [session, setSession] = useState<AccessSession | null>(AccessApi.session());
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    // Keep the query (e.g. route/bus prefilled from the map) so the user returns to the same step
    const query = Object.entries(search)
      .filter(([, v]) => typeof v === 'string' && v)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    const toLogin = () => router.replace({ pathname: '/access', params: { next: query ? `${pathname}?${query}` : pathname } } as any);
    loadSession().then(s => {
      if (!alive) return;
      setSession(s);
      setReady(true);
      if (!s || !roles.includes(s.role)) toLogin();
    });
    const off = onSessionChange(s => {
      setSession(s);
      if (!s) router.replace('/access' as any);
    });
    return () => {
      alive = false;
      off();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return { session, ready };
}

/** Grey placeholder blocks shown while content loads (instead of a blank screen). */
export function Loading({ lines = 3 }: { lines?: number }) {
  const { a } = useAccessT();
  return (
    <View accessibilityRole="progressbar" accessibilityLabel={a('loading')} style={{ marginTop: SPACING.md }}>
      {Array.from({ length: lines }).map((_, i) => (
        <View key={i} style={styles.skeletonCard}>
          <View style={[styles.skeletonLine, { width: '45%' }]} />
          <View style={[styles.skeletonLine, { width: '85%' }]} />
          <View style={[styles.skeletonLine, { width: '65%', marginBottom: 0 }]} />
        </View>
      ))}
    </View>
  );
}

export function OfflineBanner({ at }: { at?: string }) {
  return (
    <View style={styles.offline} accessibilityRole="alert">
      <Text style={styles.offlineText}>OFFLINE — SHOWING LAST KNOWN DATA{at ? ` · ${new Date(at).toLocaleString()}` : ''}</Text>
    </View>
  );
}

export const accessStyles = StyleSheet.create({
  muted: { color: COLORS.textSecondary, fontSize: 13, lineHeight: 19 },
});

const styles = StyleSheet.create({
  badge: { alignSelf: 'flex-start', borderRadius: RADIUS.full, paddingHorizontal: 10, paddingVertical: 4 },
  badgeText: { fontSize: 12, fontWeight: '800' },
  dev: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#B45309', borderRadius: RADIUS.md, padding: SPACING.sm, marginBottom: SPACING.md },
  devText: { color: '#FFFFFF', fontWeight: '800', fontSize: 12, flex: 1 },
  card: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.lg, marginBottom: SPACING.md },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  cardTitle: { fontSize: 16, fontWeight: '800', color: COLORS.deepNavy, flexShrink: 1 },
  label: { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary, marginBottom: 4 },
  input: { minHeight: 48, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, paddingHorizontal: SPACING.md, fontSize: 15, color: COLORS.textPrimary, backgroundColor: COLORS.surface },
  inputFocused: { borderColor: COLORS.primary, shadowColor: COLORS.primary, shadowOpacity: 0.18, shadowRadius: 6, shadowOffset: { width: 0, height: 0 } },
  choiceRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm, marginBottom: SPACING.md },
  choice: { flexGrow: 1, minHeight: 48, minWidth: 120, borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border, justifyContent: 'center', alignItems: 'center', paddingHorizontal: SPACING.md, backgroundColor: COLORS.surface },
  choiceActive: { borderColor: COLORS.deepNavy, backgroundColor: COLORS.deepNavy },
  choiceText: { fontWeight: '700', color: COLORS.textPrimary, textAlign: 'center' },
  choiceTextActive: { color: COLORS.textInverse },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 6, gap: SPACING.md },
  rowLabel: { color: COLORS.textSecondary, fontSize: 14 },
  rowValue: { color: COLORS.textPrimary, fontWeight: '700', fontSize: 14, flexShrink: 1, textAlign: 'right' },
  stat: { flexGrow: 1, minWidth: 100, backgroundColor: COLORS.surfaceSubtle, borderRadius: RADIUS.md, padding: SPACING.md },
  statValue: { fontSize: 22, fontWeight: '900', color: COLORS.deepNavy },
  statLabel: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  error: { color: '#8E1C1C', fontWeight: '600', marginBottom: SPACING.md },
  skeletonCard: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, padding: SPACING.lg, marginBottom: SPACING.md },
  skeletonLine: { height: 12, borderRadius: 6, backgroundColor: COLORS.surfaceSubtle, marginBottom: 10 },
  offline: { backgroundColor: '#44506A', borderRadius: RADIUS.md, padding: SPACING.sm, marginBottom: SPACING.md },
  offlineText: { color: '#FFFFFF', fontWeight: '800', fontSize: 12 },
});
