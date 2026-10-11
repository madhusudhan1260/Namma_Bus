import React, { useState } from 'react';
import { Text } from 'react-native';
import { useRouter } from 'expo-router';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { accessStyles, Card, ErrorText, Field, useAccessGuard } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';

export default function Privacy() {
  const router = useRouter();
  const { a } = useAccessT();
  useAccessGuard(['PASSENGER', 'STUDENT']);
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await AccessApi.deleteAccount(password);
      setDone(true);
      setTimeout(() => router.replace('/access' as any), 1500);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthScreen title={a('privacyTitle')}>
      <Card title={a('privacyWhat')}>
        <Text style={accessStyles.muted}>{a('privacyWhatBody')}</Text>
      </Card>
      <Card title={a('deleteAccount')}>
        <Text style={[accessStyles.muted, { marginBottom: 12 }]}>{a('deleteWarning')}</Text>
        {done ? <Notice tone="success" body={a('deleted')} /> : null}
        {!confirming ? (
          <AuthButton variant="secondary" icon="trash-outline" label={a('deleteAccount')} onPress={() => setConfirming(true)} />
        ) : (
          <>
            <Field label={a('confirmPassword')} value={password} onChangeText={setPassword} secure />
            <ErrorText text={error} />
            <AuthButton icon="trash-outline" label={a('deleteButton')} onPress={remove} loading={busy} disabled={!password} />
            <AuthButton variant="link" label={a('cancel')} onPress={() => setConfirming(false)} />
          </>
        )}
      </Card>
    </AuthScreen>
  );
}
