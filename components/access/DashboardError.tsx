import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton } from '../auth/AuthUi';
import { AccessApi } from '../../services/accessApi';

/** Shown when the user is signed in but their dashboard could not be loaded. Offers Retry and Logout. */
export function DashboardError({ detail, onRetry }: { detail?: string | null; onRetry: () => void }) {
  const { a } = useAccessT();
  return (
    <View style={styles.box} accessibilityLiveRegion="polite">
      <Ionicons name="cloud-offline-outline" size={36} color={COLORS.deepNavy} />
      <Text style={styles.title}>{a('dashboardLoadError')}</Text>
      {detail ? <Text style={styles.detail}>{detail}</Text> : null}
      <AuthButton icon="refresh" label={a('tryAgain')} onPress={onRetry} />
      <AuthButton variant="secondary" icon="log-out-outline" label={a('signOut')} onPress={() => AccessApi.logout()} />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { alignItems: 'stretch', paddingVertical: SPACING.xl, gap: SPACING.sm },
  title: { fontSize: 17, fontWeight: '800', color: COLORS.textPrimary, textAlign: 'center', marginTop: SPACING.sm },
  detail: { fontSize: 13, color: COLORS.textSecondary, textAlign: 'center', marginBottom: SPACING.sm },
});
