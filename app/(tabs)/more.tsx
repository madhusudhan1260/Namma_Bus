import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useTransit } from '../../context/TransitContext';
import { AccessAccountCard, useAccessSession } from '../../components/access/AccessAccountCard';
import { FadeIn, PressScale } from '../../components/ui/motion';

/** More tab: account, language, help/privacy, staff portals and a plain statement about data sources. */
export default function MoreScreen() {
  const router = useRouter();
  const { a, lang } = useAccessT();
  const { setPreferredLanguage } = useTransit();
  const session = useAccessSession();
  const traveller = !!session && ['PASSENGER', 'STUDENT'].includes(session.role);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title} accessibilityRole="header">{a('moreTitle')}</Text>

        <FadeIn>
          <AccessAccountCard />
        </FadeIn>

        <Text style={styles.section}>{a('language')}</Text>
        <View style={styles.card}>
          <View style={styles.langRow}>
            {(['EN', 'KN'] as const).map(l => (
              <TouchableOpacity key={l} style={[styles.lang, lang === l && styles.langActive]} onPress={() => setPreferredLanguage(l)}
                accessibilityRole="button" accessibilityState={{ selected: lang === l }}>
                <Text style={[styles.langText, lang === l && styles.langTextActive]}>{l === 'EN' ? 'English' : 'ಕನ್ನಡ'}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {!traveller ? (
          <View style={styles.card}>
            <Link icon="help-circle-outline" label={a('helpFeedback')} onPress={() => router.push('/access/help' as any)} />
          </View>
        ) : null}

        <Text style={styles.section}>{a('staffPortals')}</Text>
        <View style={styles.card}>
          <Link icon="qr-code-outline" label={a('portalConductor')} onPress={() => router.push('/access/conductor' as any)} />
          <Link icon="school-outline" label={a('portalCollege')} onPress={() => router.push('/access/college' as any)} />
          <Link icon="shield-outline" label={a('portalAdmin')} onPress={() => router.push('/access/admin' as any)} />
        </View>

        <Text style={styles.section}>{a('aboutData')}</Text>
        <View style={styles.card}>
          <Text style={styles.body}>{a('aboutDataBody')}</Text>
        </View>
        <View style={[styles.card, styles.devCard]}>
          <Text style={styles.devTitle}>{a('devStandIns')}</Text>
          <Text style={styles.body}>{a('devStandInsBody')}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function Link({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <PressScale style={styles.link} hoverLift={false} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={20} color={COLORS.deepNavy} style={{ marginRight: 12 }} />
      <Text style={styles.linkText}>{label}</Text>
      <Ionicons name="chevron-forward" size={16} color={COLORS.textMuted} />
    </PressScale>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  scroll: { padding: SPACING.md, paddingBottom: SPACING.xxxl, width: '100%', maxWidth: 760, alignSelf: 'center' },
  title: { fontSize: 24, fontWeight: '900', color: COLORS.deepNavy, marginBottom: SPACING.md },
  section: { fontSize: 14, fontWeight: '800', color: COLORS.textSecondary, marginTop: SPACING.lg, marginBottom: SPACING.sm, textTransform: 'uppercase' },
  card: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, paddingVertical: SPACING.xs || 4, marginTop: SPACING.sm },
  langRow: { flexDirection: 'row', gap: SPACING.sm, paddingVertical: SPACING.sm },
  lang: { flex: 1, minHeight: 48, borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center' },
  langActive: { backgroundColor: COLORS.deepNavy, borderColor: COLORS.deepNavy },
  langText: { fontWeight: '800', color: COLORS.textPrimary },
  langTextActive: { color: COLORS.textInverse },
  link: { flexDirection: 'row', alignItems: 'center', minHeight: 52, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  linkText: { flex: 1, fontSize: 15, fontWeight: '600', color: COLORS.textPrimary },
  body: { color: COLORS.textSecondary, lineHeight: 20, paddingVertical: SPACING.sm },
  devCard: { backgroundColor: '#FFF4DB', borderColor: '#F3D58A' },
  devTitle: { fontWeight: '800', color: '#7A4B00', paddingTop: SPACING.sm },
});
