import React, { useEffect, useState } from 'react';
import { Linking, Platform, StyleSheet, Switch, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { COLORS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { accessStyles, Card, DevBanner, ErrorText, Field, Loading, Row, useAccessGuard } from '../../components/access/AccessUi';
import { AADHAAR_PICKER_SUPPORTED, AadhaarFilePicker } from '../../components/access/AadhaarFilePicker';
import { AccessApi, PickedFile } from '../../services/accessApi';

type Step = 'QUESTION' | 'NO_AADHAAR' | 'EKYC' | 'DONE';

/**
 * Female passenger identity: "Do you have an Aadhaar card?" → upload the UIDAI Aadhaar Paperless Offline e-KYC
 * file with its share code. The server checks UIDAI's digital signature; only name match, DOB, gender and the
 * signed photo (face-match reference, encrypted) are kept. The Aadhaar number is never asked for or stored.
 */
export default function AadhaarVerification() {
  const router = useRouter();
  const { a } = useAccessT();
  const { ready } = useAccessGuard(['PASSENGER', 'STUDENT']);
  const [me, setMe] = useState<any>(null);
  const [info, setInfo] = useState<{ available: boolean; zip_available: boolean; pdf_available: boolean; max_age_hours: number; download_url: string } | null>(null);
  const [step, setStep] = useState<Step>('QUESTION');
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<PickedFile | null>(null);
  const [secret, setSecret] = useState('');
  const isPdf = file?.type === 'application/pdf';
  const secretOk = isPdf ? /^[A-Za-z]{1,4}\d{4}$/.test(secret) : /^\d{4}$/.test(secret);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ready) return;
    AccessApi.me()
      .then(m => {
        setMe(m);
        if (m?.passenger?.identity_status === 'VERIFIED') setStep('DONE');
        else if (m?.passenger?.has_aadhaar_answer === true) setStep('EKYC');
      })
      .catch(e => setError(e.message));
    AccessApi.ekycInfo().then(setInfo).catch(() => setInfo(null));
  }, [ready]);

  const answer = async (has: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await AccessApi.aadhaarAnswer(has);
      setStep(has ? 'EKYC' : 'NO_AADHAAR');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const upload = async () => {
    if (!consent) return setError(a('ekycConsentRequired'));
    if (!file) return setError(a('ekycChooseFile'));
    if (isPdf && !info?.pdf_available) return setError(a('ekycTypeOff'));
    if (!isPdf && !info?.zip_available) return setError(a('ekycTypeOff'));
    if (!secretOk) return setError(isPdf ? a('pdfPasswordInvalid') : a('ekycShareCodeInvalid'));
    setBusy(true);
    setError(null);
    try {
      setResult(await AccessApi.aadhaarUpload(file, isPdf ? secret.toUpperCase() : secret));
      setSecret('');
      setFile(null);
      setStep('DONE');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const devSimulator = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await AccessApi.identityStart();
      if (Platform.OS === 'web') window.location.assign(r.authorization_url);
      else await Linking.openURL(r.authorization_url);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const nextAfter = () =>
    router.replace((me?.role === 'STUDENT' && me?.student?.status === 'NOT_SUBMITTED' ? '/access/student' : '/(tabs)') as any);

  if (!me) {
    return (
      <AuthScreen title={a('identityVerification')}>
        <ErrorText text={error} />
        <Loading lines={2} />
      </AuthScreen>
    );
  }
  const svc = me.passenger || {};

  if (step === 'NO_AADHAAR') {
    return (
      <AuthScreen title={a('regularTickets')} footer={<AuthButton label={a('continue')} icon="arrow-forward" onPress={nextAfter} />}>
        <Notice tone="info" body={a('noAadhaarMsg')} />
      </AuthScreen>
    );
  }

  if (step === 'DONE') {
    return (
      <AuthScreen
        title={a('identityVerification')}
        footer={
          <>
            <AuthButton label={a('buyTicket')} icon="ticket-outline" onPress={() => router.replace('/access/buy' as any)} />
            <AuthButton variant="secondary" label={a('continue')} onPress={nextAfter} />
          </>
        }
      >
        <Notice tone="success" title={a('ekycVerifiedTitle')} body={result?.message || a('ekycVerifiedBody')} />
        {result ? (
          <Card>
            <Row label={a('ekycGender')} value={result.gender_attested === 'F' ? a('female') : result.gender_attested === 'M' ? a('male') : result.gender_attested} />
            {result.date_of_birth ? <Row label={a('dobLabel')} value={result.date_of_birth} /> : null}
            <Row label={a('validUntil')} value={new Date(result.expires_at).toLocaleDateString()} />
            {!result.name_matches_account ? <Text style={styles.warn}>{a('ekycNameMismatch')}</Text> : null}
          </Card>
        ) : null}
        <Text style={accessStyles.muted}>{a('ekycFaceNext')}</Text>
      </AuthScreen>
    );
  }

  if (step === 'EKYC') {
    const available = !!info?.available;
    return (
      <AuthScreen
        title={a('ekycTitle')}
        subtitle={a('ekycSub')}
        footer={
          <>
            {available && AADHAAR_PICKER_SUPPORTED ? (
              <AuthButton icon="shield-checkmark-outline" label={a('ekycVerifyButton')} onPress={upload} loading={busy}
                disabled={!consent || !file || !secretOk} />
            ) : null}
            <AuthButton variant="secondary" label={a('ekycLater')} onPress={nextAfter} />
          </>
        }
      >
        <Card title={a('pdfHowTitle')}>
          <Text style={styles.stepText}>1. {a('pdfHow1')}</Text>
          <AuthButton variant="link" icon="open-outline" label="myaadhaar.uidai.gov.in" onPress={() => Linking.openURL('https://myaadhaar.uidai.gov.in/')} />
          <Text style={styles.stepText}>2. {a('pdfHow2')}</Text>
          <Text style={styles.small}>{a('pdfHowAlt', { h: info?.max_age_hours ?? 72 })}</Text>
        </Card>

        <Card title={a('ekycSecurityTitle')}>
          <Text style={styles.bullet}>• {a('ekycSec1')}</Text>
          <Text style={styles.bullet}>• {a('ekycSec2')}</Text>
          <Text style={styles.bullet}>• {a('ekycSec3')}</Text>
          <Text style={styles.bullet}>• {a('ekycSec4')}</Text>
          <View style={styles.consentRow}>
            <Switch value={consent} onValueChange={setConsent} accessibilityLabel={a('ekycConsentLabel')} />
            <Text style={styles.consentText}>{a('ekycConsentLabel')}</Text>
          </View>
        </Card>

        {!available ? <Notice tone="warning" body={a('ekycNotConfigured')} /> : null}
        {available && !AADHAAR_PICKER_SUPPORTED ? <Notice tone="info" body={a('ekycUseWeb')} /> : null}
        {available && AADHAAR_PICKER_SUPPORTED ? (
          <>
            <AadhaarFilePicker label={a('ekycFileLabel')} hint={a('ekycFileHint')} dropHint={a('dropHere')} file={file}
              onPicked={f => { setFile(f); setSecret(''); setError(null); }} onError={setError} />
            {file ? (
              isPdf ? (
                <Field label={a('pdfPassword')} value={secret} onChangeText={v => setSecret(v.replace(/[^A-Za-z0-9]/g, '').slice(0, 8).toUpperCase())}
                  autoCapitalize="characters" placeholder="ASHA1995" secure />
              ) : (
                <Field label={a('ekycShareCode')} value={secret} onChangeText={v => setSecret(v.replace(/\D/g, '').slice(0, 4))} keyboardType="number-pad" secure />
              )
            ) : null}
            {file && isPdf ? <Text style={styles.small}>{a('pdfPasswordHint')}</Text> : null}
          </>
        ) : null}
        <ErrorText text={error} />

        {svc.identity_service_is_development && svc.identity_service_available ? (
          <View style={styles.dev}>
            <DevBanner />
            <AuthButton variant="link" label={a('continueDev')} onPress={devSimulator} />
          </View>
        ) : null}
      </AuthScreen>
    );
  }

  return (
    <AuthScreen
      title={a('aadhaarQuestion')}
      subtitle={`${a('hello')} ${me.name}`}
      footer={
        <>
          <AuthButton label={a('yesAadhaar')} icon="checkmark-circle-outline" onPress={() => answer(true)} loading={busy} />
          <AuthButton variant="secondary" label={a('noAadhaar')} onPress={() => answer(false)} />
        </>
      }
    >
      <Text style={[accessStyles.muted, { marginBottom: 16 }]}>{a('aadhaarWhy')}</Text>
      <ErrorText text={error} />
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  stepText: { color: COLORS.textPrimary, fontSize: 14, lineHeight: 21, marginBottom: 4 },
  bullet: { color: COLORS.textSecondary, fontSize: 13, lineHeight: 20, marginBottom: 2 },
  consentRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginTop: SPACING.md },
  consentText: { flex: 1, color: COLORS.textPrimary, fontWeight: '700', fontSize: 13 },
  warn: { color: '#7A4B00', fontSize: 13, marginTop: 6 },
  dev: { marginTop: SPACING.lg },
  small: { color: COLORS.textSecondary, fontSize: 12, lineHeight: 18, marginTop: 4 },
});
