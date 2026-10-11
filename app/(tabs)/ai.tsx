import React, { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AssistantReply, NetworkApi } from '../../services/networkApi';
import { FadeIn, PressScale, TypingDots, stagger } from '../../components/ui/motion';

type Msg = { id: number; from: 'user' | 'bot'; text: string; actions?: AssistantReply['actions'] };

/** Assistant that answers only from the real BMTC network and live feed (no invented buses or times). */
export default function AssistantScreen() {
  const router = useRouter();
  const { a, lang } = useAccessT();
  const [msgs, setMsgs] = useState<Msg[]>([{ id: 0, from: 'bot', text: a('aiWelcome') }]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const scroll = useRef<ScrollView>(null);
  const nextId = useRef(1);
  const inFlight = useRef(false); // blocks a second send in the same tick (Enter + tap, double tap)

  const send = async (q?: string) => {
    const message = (q ?? text).trim();
    if (!message || busy || inFlight.current) return;
    inFlight.current = true;
    setText('');
    setMsgs(m => [...m, { id: nextId.current++, from: 'user', text: message }]);
    setBusy(true);
    try {
      const r = await NetworkApi.assistant(message, lang);
      setMsgs(m => [...m, { id: nextId.current++, from: 'bot', text: r.answer, actions: r.actions }]);
    } catch (e: any) {
      setMsgs(m => [...m, { id: nextId.current++, from: 'bot', text: e?.message || 'Unavailable' }]);
    } finally {
      inFlight.current = false;
      setBusy(false);
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
    }
  };

  const actionLabel = (l: string) =>
    l === 'map' ? a('quickMap')
      : l === 'ticket' ? a('planBuy')
        : l === 'verify' ? a('verifyIdentity')
          : l === 'student' ? a('studentVerification')
            : l === 'tickets' ? a('myTickets')
              : `${a('planViewRoute')} ${l}`;

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Text style={styles.title} accessibilityRole="header">{a('aiTitle')}</Text>
          <Text style={styles.sub}>{a('aiSub')}</Text>
        </View>
        <ScrollView ref={scroll} contentContainerStyle={styles.list} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: false })}>
          {msgs.map(m => (
            <FadeIn key={m.id} from={m.from === 'user' ? 'right' : 'left'} distance={18} duration={340}
              style={[styles.bubble, m.from === 'user' ? styles.user : styles.bot]}>
            <View accessibilityLiveRegion={m.from === 'bot' ? 'polite' : 'none'}>
              <Text style={m.from === 'user' ? styles.userText : styles.botText}>{m.text}</Text>
              {m.actions?.length ? (
                <View style={styles.actions}>
                  {m.actions.map((act, i) => (
                    <PressScale key={i} style={styles.action} hoverLift={false} onPress={() => router.push(act.href as any)} accessibilityRole="button">
                      <Text style={styles.actionText}>{actionLabel(act.label)}</Text>
                    </PressScale>
                  ))}
                </View>
              ) : null}
            </View>
            </FadeIn>
          ))}
          {busy ? (
            <FadeIn from="left" distance={12} duration={240} style={[styles.bubble, styles.bot, { paddingVertical: 14 }]}>
              <TypingDots />
            </FadeIn>
          ) : null}
          <View style={styles.examples}>
            {[a('aiExample1'), a('aiExample2'), a('aiExample3'), a('aiExample4')].map((ex, i) => (
              <FadeIn key={ex} delay={200 + stagger(i, 70)}>
                <PressScale style={styles.example} onPress={() => send(ex)} accessibilityRole="button" accessibilityLabel={ex}>
                  <Text style={styles.exampleText}>{ex}</Text>
                </PressScale>
              </FadeIn>
            ))}
          </View>
        </ScrollView>
        <View style={styles.inputBar}>
          <TextInput style={styles.input} value={text} onChangeText={setText} placeholder={a('aiPlaceholder')} placeholderTextColor={COLORS.textMuted}
            onSubmitEditing={() => send()} returnKeyType="send" accessibilityLabel={a('aiPlaceholder')} />
          <TouchableOpacity style={[styles.send, !text.trim() && { opacity: 0.5 }]} onPress={() => send()} disabled={!text.trim() || busy} accessibilityRole="button" accessibilityLabel={a('aiSend')}>
            <Ionicons name="send" size={18} color={COLORS.textInverse} />
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  header: { paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface },
  title: { fontSize: 20, fontWeight: '900', color: COLORS.deepNavy },
  sub: { fontSize: 12, color: COLORS.textSecondary, marginTop: 2 },
  list: { padding: SPACING.md, width: '100%', maxWidth: 760, alignSelf: 'center' },
  bubble: { maxWidth: '88%', borderRadius: RADIUS.lg, padding: SPACING.md, marginBottom: SPACING.sm },
  user: { alignSelf: 'flex-end', backgroundColor: COLORS.deepNavy },
  bot: { alignSelf: 'flex-start', backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  userText: { color: COLORS.textInverse, fontSize: 15 },
  botText: { color: COLORS.textPrimary, fontSize: 15, lineHeight: 21 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: SPACING.sm },
  action: { minHeight: 36, paddingHorizontal: 12, borderRadius: RADIUS.full, borderWidth: 1.5, borderColor: COLORS.primary, justifyContent: 'center' },
  actionText: { color: COLORS.primaryDark, fontWeight: '700', fontSize: 13 },
  examples: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: SPACING.md },
  example: { minHeight: 40, paddingHorizontal: 14, borderRadius: RADIUS.full, backgroundColor: COLORS.surfaceSubtle, justifyContent: 'center' },
  exampleText: { color: COLORS.deepNavy, fontWeight: '700' },
  inputBar: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border, backgroundColor: COLORS.surface },
  input: { flex: 1, minHeight: 48, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.full, paddingHorizontal: SPACING.md, fontSize: 15, color: COLORS.textPrimary },
  send: { width: 48, height: 48, borderRadius: 24, backgroundColor: COLORS.deepNavy, alignItems: 'center', justifyContent: 'center' },
});
