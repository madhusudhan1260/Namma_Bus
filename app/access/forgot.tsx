import React, { useState } from 'react';
import { useRouter } from 'expo-router';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { ErrorText, Field } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';

/** Forgot password: a 6-digit code is emailed (valid 15 minutes, 5 tries); resetting signs out every device. */
export default function ForgotPassword() {
  const router = useRouter();
  const { a } = useAccessT();
  const [identifier, setIdentifier] = useState('');
  const [sent, setSent] = useState<{ dev?: string; notice?: string } | null>(null);
  const [code, setCode] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (identifier.trim().length < 3) return setError(a('mobileOrEmail'));
    setBusy(true);
    setError(null);
    try {
      const r = await AccessApi.forgotPassword(identifier.trim());
      setSent({ dev: r.development_code, notice: r.development_notice });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return setError(a('errPassword'));
    if (pw !== pw2) return setError(a('passwordsDontMatch'));
    setBusy(true);
    setError(null);
    try {
      await AccessApi.resetPassword(identifier.trim(), code.trim(), pw);
      setDone(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <AuthScreen title={a('forgotPassword')} footer={<AuthButton label={a('login')} icon="log-in-outline" onPress={() => router.replace('/access' as any)} />}>
        <Notice tone="success" body={a('passwordChanged')} />
      </AuthScreen>
    );
  }

  return (
    <AuthScreen
      title={a('forgotPassword')}
      subtitle={a('forgotSub')}
      footer={
        sent ? (
          <AuthButton label={a('setNewPassword')} icon="key-outline" onPress={reset} loading={busy} disabled={code.trim().length !== 6} />
        ) : (
          <AuthButton label={a('sendCode')} icon="mail-outline" onPress={send} loading={busy} />
        )
      }
    >
      <Field label={a('mobileOrEmail')} value={identifier} onChangeText={setIdentifier} keyboardType="email-address" />
      {sent ? (
        <>
          <Notice tone="info" body={a('resetCodeSent')} />
          {sent.dev ? <Notice tone="demo" title={sent.notice} body={`Development code: ${sent.dev}`} /> : null}
          <Field label={a('emailCode')} value={code} onChangeText={v => setCode(v.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" />
          <Field label={a('newPassword')} value={pw} onChangeText={setPw} secure />
          <Field label={a('confirmPassword')} value={pw2} onChangeText={setPw2} secure />
        </>
      ) : null}
      <ErrorText text={error} />
      <AuthButton variant="link" label={a('backToLogin')} onPress={() => router.replace('/access' as any)} />
    </AuthScreen>
  );
}
