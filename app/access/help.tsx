import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useTransit } from '../../context/TransitContext';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { accessStyles, Card, Choice, ErrorText, Field } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';

const FAQ: { q: { EN: string; KN: string }; a: { EN: string; KN: string } }[] = [
  {
    q: { EN: 'Why is a bus marked Recent or Stale?', KN: 'ಬಸ್ ಅನ್ನು ಇತ್ತೀಚಿನ ಅಥವಾ ಹಳೆಯದು ಎಂದು ಏಕೆ ತೋರಿಸಲಾಗಿದೆ?' },
    a: {
      EN: 'Live = position updated in the last minute. Recent = 1–2 minutes old. Stale = older (up to 5 minutes). Positions come from BMTC and can be delayed.',
      KN: 'ಲೈವ್ = ಕಳೆದ ಒಂದು ನಿಮಿಷದಲ್ಲಿ ನವೀಕರಿಸಲಾಗಿದೆ. ಇತ್ತೀಚಿನ = 1–2 ನಿಮಿಷ ಹಳೆಯದು. ಹಳೆಯದು = ಅದಕ್ಕಿಂತ ಹಳೆಯದು (5 ನಿಮಿಷದವರೆಗೆ). ಸ್ಥಳಗಳು BMTC ಯಿಂದ ಬರುತ್ತವೆ ಮತ್ತು ತಡವಾಗಬಹುದು.',
    },
  },
  {
    q: { EN: 'How do I get a free ticket?', KN: 'ಉಚಿತ ಟಿಕೆಟ್ ಹೇಗೆ ಪಡೆಯುವುದು?' },
    a: {
      EN: 'Only verified eligibility gives a ₹0 ticket: a college-approved, valid student bus pass, or a verified identity plus face check under the configured policy. Uploading documents or choosing a gender alone never makes a ticket free.',
      KN: 'ಪರಿಶೀಲಿತ ಅರ್ಹತೆ ಇದ್ದರೆ ಮಾತ್ರ ₹0 ಟಿಕೆಟ್: ಕಾಲೇಜು ಅನುಮೋದಿಸಿದ ಮಾನ್ಯ ವಿದ್ಯಾರ್ಥಿ ಪಾಸ್, ಅಥವಾ ನೀತಿಯ ಪ್ರಕಾರ ಪರಿಶೀಲಿತ ಗುರುತು ಮತ್ತು ಮುಖ ಪರಿಶೀಲನೆ. ದಾಖಲೆ ಅಪ್‌ಲೋಡ್ ಅಥವಾ ಲಿಂಗದ ಆಯ್ಕೆಯಿಂದ ಮಾತ್ರ ಟಿಕೆಟ್ ಉಚಿತವಾಗುವುದಿಲ್ಲ.',
    },
  },
  {
    q: { EN: 'Can I show my ticket without internet?', KN: 'ಇಂಟರ್ನೆಟ್ ಇಲ್ಲದೆ ಟಿಕೆಟ್ ತೋರಿಸಬಹುದೇ?' },
    a: {
      EN: 'Yes. Open My tickets once while online; issued tickets and their QR are saved on your device.',
      KN: 'ಹೌದು. ಆನ್‌ಲೈನ್ ಇರುವಾಗ ಒಮ್ಮೆ ನನ್ನ ಟಿಕೆಟ್‌ಗಳನ್ನು ತೆರೆಯಿರಿ; ನೀಡಲಾದ ಟಿಕೆಟ್‌ಗಳು ಮತ್ತು QR ನಿಮ್ಮ ಸಾಧನದಲ್ಲಿ ಉಳಿಯುತ್ತವೆ.',
    },
  },
  {
    q: { EN: 'How long does student verification take?', KN: 'ವಿದ್ಯಾರ್ಥಿ ಪರಿಶೀಲನೆಗೆ ಎಷ್ಟು ಸಮಯ ಬೇಕು?' },
    a: {
      EN: 'Your college reviews the request. Until it is approved you pay the normal fare. If rejected, the reason is shown and you can submit again.',
      KN: 'ನಿಮ್ಮ ಕಾಲೇಜು ವಿನಂತಿಯನ್ನು ಪರಿಶೀಲಿಸುತ್ತದೆ. ಅನುಮೋದನೆಯವರೆಗೆ ನೀವು ಸಾಮಾನ್ಯ ದರ ಪಾವತಿಸುತ್ತೀರಿ. ತಿರಸ್ಕರಿಸಿದರೆ ಕಾರಣ ತೋರಿಸಲಾಗುತ್ತದೆ ಮತ್ತು ಮತ್ತೆ ಸಲ್ಲಿಸಬಹುದು.',
    },
  },
];

export default function Help() {
  const { a } = useAccessT();
  const { preferredLanguage } = useTransit();
  const lang = preferredLanguage === 'KN' ? 'KN' : 'EN';
  const [open, setOpen] = useState<number | null>(0);
  const [category, setCategory] = useState('BUS_LOCATION');
  const [message, setMessage] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await AccessApi.feedback(category, message.trim(), 'help');
      setDone(a('sent'));
      setMessage('');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthScreen title={a('helpTitle')}>
      <Card title={a('faqTitle')}>
        {FAQ.map((f, i) => (
          <View key={i} style={styles.faq}>
            <TouchableOpacity style={styles.q} onPress={() => setOpen(open === i ? null : i)} accessibilityRole="button" accessibilityState={{ expanded: open === i }}>
              <Text style={styles.qText}>{f.q[lang]}</Text>
              <Ionicons name={open === i ? 'chevron-up' : 'chevron-down'} size={18} color={COLORS.textSecondary} />
            </TouchableOpacity>
            {open === i ? <Text style={styles.aText}>{f.a[lang]}</Text> : null}
          </View>
        ))}
      </Card>
      <Card title={a('reportTitle')}>
        <Text style={accessStyles.muted}>{a('category')}</Text>
        <Choice
          options={[
            { value: 'BUS_LOCATION', label: a('catBus') },
            { value: 'TICKET', label: a('catTicket') },
            { value: 'PAYMENT', label: a('catPayment') },
            { value: 'VERIFICATION', label: a('catVerification') },
            { value: 'APP_PROBLEM', label: a('catApp') },
            { value: 'OTHER', label: a('catOther') },
          ]}
          value={category}
          onChange={setCategory}
        />
        <Field label={a('describeProblem')} value={message} onChangeText={setMessage} multiline autoCapitalize="sentences" />
        <Text style={[accessStyles.muted, { marginBottom: SPACING.md }]}>{a('noPersonalDocs')}</Text>
        {done ? <Notice tone="success" body={done} /> : null}
        <ErrorText text={error} />
        <AuthButton icon="send-outline" label={a('send')} onPress={send} loading={busy} disabled={message.trim().length < 5} />
      </Card>
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  faq: { borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  q: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 48, gap: SPACING.sm },
  qText: { flex: 1, fontWeight: '700', color: COLORS.textPrimary },
  aText: { color: COLORS.textSecondary, lineHeight: 20, paddingBottom: SPACING.md },
});
