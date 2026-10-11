import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, SPACING } from '../constants/theme';
import { useAccessT } from '../constants/accessI18n';
import { FadeIn, PressScale, stagger } from '../components/ui/motion';
import { screenStyles } from '../components/ui/screenStyles';

const PLUM = '#B1285F';
const STEPS: { icon: keyof typeof Ionicons.glyphMap; color: string; title: string; body: string; href?: string }[] = [
  { icon: 'navigate-outline', color: '#F7B21B', title: 'guide1Title', body: 'guide1Body', href: '/(tabs)' },
  { icon: 'location-outline', color: '#F0506E', title: 'guide2Title', body: 'guide2Body', href: '/(tabs)/map' },
  { icon: 'bus-outline', color: '#EF7D12', title: 'guide3Title', body: 'guide3Body', href: '/(tabs)/map' },
  { icon: 'calculator-outline', color: '#9AA23A', title: 'guide4Title', body: 'guide4Body', href: '/fare' },
  { icon: 'ticket-outline', color: '#12355B', title: 'guide5Title', body: 'guide5Body', href: '/access/buy' },
  { icon: 'shield-checkmark-outline', color: '#2E8BF0', title: 'guide6Title', body: 'guide6Body', href: '/access/aadhaar' },
  { icon: 'school-outline', color: '#1FBF7F', title: 'guide7Title', body: 'guide7Body', href: '/access/student' },
  { icon: 'sparkles-outline', color: '#7B3FB8', title: 'guide8Title', body: 'guide8Body', href: '/(tabs)/ai' },
  { icon: 'language-outline', color: PLUM, title: 'guide9Title', body: 'guide9Body' },
];

/** How to use ನಮ್ಮ Bus — short, illustrated steps that link straight to each feature (English / Kannada). */
export default function GuideScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={[styles.header, { backgroundColor: PLUM }]}>
        <PressScale onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)' as any))} style={styles.back} accessibilityRole="button" accessibilityLabel={a('back')}>
          <Ionicons name="chevron-back" size={22} color="#FFFFFF" />
        </PressScale>
        <Ionicons name="book-outline" size={22} color="#FFFFFF" />
        <Text style={styles.headerTitle} accessibilityRole="header">{a('tileGuide')}</Text>
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <FadeIn><Text style={styles.intro}>{a('guideIntro')}</Text></FadeIn>
        {STEPS.map((s, i) => (
          <FadeIn key={s.title} delay={stagger(i, 70)}>
            <PressScale style={styles.step} onPress={() => s.href && router.push(s.href as any)} disabled={!s.href} accessibilityRole={s.href ? 'button' : 'text'}
              accessibilityLabel={`${i + 1}. ${a(s.title as any)}`}>
              <View style={[styles.num, { backgroundColor: s.color }]}>
                <Ionicons name={s.icon} size={22} color="#FFFFFF" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.stepTitle}>{i + 1}. {a(s.title as any)}</Text>
                <Text style={styles.stepBody}>{a(s.body as any)}</Text>
              </View>
              {s.href ? <Ionicons name="chevron-forward" size={18} color={COLORS.textMuted} /> : null}
            </PressScale>
          </FadeIn>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  ...screenStyles,
  intro: { color: COLORS.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: SPACING.md },
  step: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#FFFFFF', borderRadius: 16, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: COLORS.border },
  num: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  stepTitle: { fontWeight: '900', color: COLORS.textPrimary, fontSize: 15 },
  stepBody: { color: COLORS.textSecondary, fontSize: 13, lineHeight: 19, marginTop: 2 },
});
