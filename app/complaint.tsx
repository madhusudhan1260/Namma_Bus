import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Linking, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAccessT } from '../constants/accessI18n';
import { AccessApi } from '../services/accessApi';
import { FeatureShell, GradientButton } from '../components/feature/FeatureShell';
import { OutlinedInput } from '../components/feature/Inputs';
import { EmptyState } from '../components/feature/EmptyState';
import { FadeIn, PressScale, stagger } from '../components/ui/motion';

const native = Platform.OS !== 'web';
const PURPLE = '#7C3AED';
const TYPES: { key: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'cmpRash', icon: 'speedometer-outline' },
  { key: 'cmpRude', icon: 'sad-outline' },
  { key: 'cmpHarassment', icon: 'hand-left-outline' },
  { key: 'cmpNoStop', icon: 'close-circle-outline' },
  { key: 'cmpCrowd', icon: 'people-outline' },
  { key: 'cmpClean', icon: 'trash-outline' },
  { key: 'cmpFare', icon: 'cash-outline' },
  { key: 'cmpOther', icon: 'ellipsis-horizontal-circle-outline' },
];

const nowText = () => {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

/** Raise a complaint about a bus journey. Sent to the Namma Bus team (shown honestly — not to BMTC directly). */
export default function ComplaintScreen() {
  const router = useRouter();
  const { a } = useAccessT();
  const [type, setType] = useState<string | null>(null);
  const [bus, setBus] = useState('');
  const [route, setRoute] = useState('');
  const [when, setWhen] = useState(nowText());
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ref, setRef] = useState<string | null>(null);
  const tick = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (ref) Animated.spring(tick, { toValue: 1, speed: 10, bounciness: 14, useNativeDriver: native }).start();
  }, [ref, tick]);

  const submit = async () => {
    if (!type) return setError(a('cmpChooseType'));
    if (text.trim().length < 10) return setError(a('cmpDescribe'));
    setBusy(true);
    setError(null);
    try {
      const message = [`[${a(type as any)}]`, bus.trim() && `Bus: ${bus.trim().toUpperCase()}`, route.trim() && `Route: ${route.trim().toUpperCase()}`,
        when.trim() && `When: ${when.trim()}`, text.trim()].filter(Boolean).join('\n');
      const r = await AccessApi.feedback('COMPLAINT', message, 'complaint');
      setRef((r?.id || '').slice(0, 8).toUpperCase() || 'SENT');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (ref) {
    return (
      <FeatureShell title={a('tileComplaint')} icon="document-text-outline" color={PURPLE} aside={<EmptyState title={a('cmpThanks')} message={a('cmpThanksMsg')} />}>
        <View style={styles.done}>
          <Animated.View style={[styles.tick, { transform: [{ scale: tick }] }]}><Ionicons name="checkmark" size={54} color="#FFFFFF" /></Animated.View>
          <Text style={styles.doneTitle}>{a('cmpSent')}</Text>
          <Text style={styles.doneRef}>{a('cmpRef', { ref })}</Text>
          <Text style={styles.doneMsg}>{a('cmpWhereGoes')}</Text>
          <GradientButton label={a('fsHome')} icon="home-outline" onPress={() => router.replace('/(tabs)' as any)} />
        </View>
      </FeatureShell>
    );
  }

  return (
    <FeatureShell title={a('tileComplaint')} icon="document-text-outline" color={PURPLE}
      aside={<EmptyState title={a('cmpAsideTitle')} message={a('cmpAsideMsg')} />}>
      <Text style={styles.label}>{a('cmpWhat')}</Text>
      <View style={styles.types}>
        {TYPES.map((t, i) => (
          <FadeIn key={t.key} delay={stagger(i, 35)} style={styles.typeCell}>
            <PressScale hoverLift={false} style={[styles.type, type === t.key && styles.typeOn]} onPress={() => setType(t.key)} accessibilityRole="radio" accessibilityState={{ selected: type === t.key }}>
              <Ionicons name={t.icon} size={20} color={type === t.key ? '#FFFFFF' : PURPLE} />
              <Text style={[styles.typeText, type === t.key && { color: '#FFFFFF' }]} numberOfLines={2}>{a(t.key as any)}</Text>
            </PressScale>
          </FadeIn>
        ))}
      </View>
      {type === 'cmpHarassment' ? (
        <FadeIn style={styles.alert}>
          <Ionicons name="warning" size={20} color="#B91C1C" />
          <Text style={styles.alertText}>{a('cmpDanger')}</Text>
          <PressScale hoverLift={false} style={styles.alertBtn} onPress={() => Linking.openURL('tel:112')} accessibilityRole="button"><Text style={styles.alertBtnText}>112</Text></PressScale>
        </FadeIn>
      ) : null}
      <View style={styles.row2}>
        <View style={{ flex: 1 }}><OutlinedInput label={a('cmpBus')} value={bus} onChangeText={setBus} placeholder="KA 57 F 4578" autoCapitalize="characters" /></View>
        <View style={{ flex: 1 }}><OutlinedInput label={a('cmpRoute')} value={route} onChangeText={setRoute} placeholder="500-D" autoCapitalize="characters" /></View>
      </View>
      <View style={{ marginTop: 14 }}><OutlinedInput label={a('cmpWhen')} value={when} onChangeText={setWhen} /></View>
      <Text style={[styles.label, { marginTop: 16 }]}>{a('cmpDetails')}</Text>
      <TextInput value={text} onChangeText={setText} multiline placeholder={a('cmpPlaceholder')} placeholderTextColor="#999" style={styles.textarea}
        accessibilityLabel={a('cmpDetails')} maxLength={1500} />
      <Text style={styles.count}>{text.length}/1500</Text>
      {error ? <Text style={styles.warn}>{error}</Text> : null}
      <GradientButton label={busy ? a('cmpSending') : a('cmpSubmit')} icon="send" onPress={submit} busy={busy} />
      <Text style={styles.note}>{a('cmpWhereGoes')}</Text>
    </FeatureShell>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 15, fontWeight: '800', color: '#1E1E24', marginBottom: 10 },
  types: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  typeCell: { width: '48%' as any, flexGrow: 1 },
  type: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 52, borderRadius: 12, borderWidth: 1.5, borderColor: '#DDD6FE', paddingHorizontal: 10, backgroundColor: '#FFFFFF' },
  typeOn: { backgroundColor: PURPLE, borderColor: PURPLE },
  typeText: { flex: 1, fontSize: 13, fontWeight: '700', color: '#3B2A6B' },
  alert: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#FEE2E2', borderRadius: 12, padding: 12, marginTop: 12 },
  alertText: { flex: 1, color: '#7F1D1D', fontSize: 13, fontWeight: '600' },
  alertBtn: { backgroundColor: '#DC2626', borderRadius: 18, paddingHorizontal: 14, minHeight: 36, justifyContent: 'center' },
  alertBtnText: { color: '#FFFFFF', fontWeight: '900' },
  row2: { flexDirection: 'row', gap: 10, marginTop: 18 },
  textarea: { minHeight: 120, borderWidth: 1, borderColor: '#B9BCC3', borderRadius: 4, padding: 12, fontSize: 15, color: '#1E1E24', textAlignVertical: 'top' },
  count: { alignSelf: 'flex-end', color: '#999', fontSize: 11, marginTop: 4 },
  warn: { color: '#B91C1C', marginTop: 8, fontWeight: '600' },
  note: { color: '#777', fontSize: 12, marginTop: 12, lineHeight: 17 },
  done: { alignItems: 'center', paddingTop: 20 },
  tick: { width: 96, height: 96, borderRadius: 48, backgroundColor: '#16A34A', alignItems: 'center', justifyContent: 'center' },
  doneTitle: { fontSize: 22, fontWeight: '900', color: '#1E1E24', marginTop: 18 },
  doneRef: { fontSize: 15, color: '#555', marginTop: 6 },
  doneMsg: { fontSize: 13, color: '#777', textAlign: 'center', marginVertical: 16, lineHeight: 19 },
});
