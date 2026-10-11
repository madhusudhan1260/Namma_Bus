import React, { useState } from 'react';
import { Text } from 'react-native';
import { useRouter } from 'expo-router';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice, isValidEmail } from '../../components/auth/AuthUi';
import { accessStyles, Card, ErrorText, Field } from '../../components/access/AccessUi';
import { DocumentPicker } from '../../components/access/DocumentPicker';
import { AccessApi, PickedFile } from '../../services/accessApi';

const FIELDS = [
  ['college_name', 'collegeName', 'words'],
  ['affiliation', 'affiliation', 'words'],
  ['address', 'address', 'sentences'],
  ['city', 'city', 'words'],
  ['state', 'state', 'words'],
  ['official_email', 'officialEmail', 'none'],
  ['phone', 'phone', 'none'],
  ['website', 'websiteOptional', 'none'],
  ['officer_name', 'officerName', 'words'],
  ['officer_designation', 'officerDesignation', 'words'],
] as const;

/**
 * College self-registration. The college starts as PENDING and is only shown to students after a
 * Super Admin reviews the authorization document and approves it. Nothing is approved automatically.
 */
export default function CollegeRegister() {
  const router = useRouter();
  const { a } = useAccessT();
  const [form, setForm] = useState<Record<string, string>>({ state: 'Karnataka', city: 'Bengaluru' });
  const [password, setPassword] = useState('');
  const [doc, setDoc] = useState<PickedFile | null>(null);
  const [result, setResult] = useState<{ college_id: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    const missing = FIELDS.filter(([k]) => k !== 'website' && !(form[k] || '').trim());
    if (missing.length) return setError(a('fillRequired'));
    if (!isValidEmail(form.official_email || '')) return setError(a('errEmail'));
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) return setError(a('errPassword'));
    if (!doc) return setError(a('uploadAuthorization'));
    setBusy(true);
    setError(null);
    try {
      setResult(await AccessApi.registerCollege({ ...form, password }, doc));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <AuthScreen title={a('registerCollege')} footer={<AuthButton label={a('backToLogin')} onPress={() => router.replace('/access' as any)} />}>
        <Notice tone="info" title={a('pendingAdminApproval')} body={result.message} />
        <Card>
          <Text style={accessStyles.muted}>{a('yourCollegeId')}</Text>
          <Text style={{ fontSize: 22, fontWeight: '900' }}>{result.college_id}</Text>
          <Text style={accessStyles.muted}>{a('collegeIdKeep')}</Text>
        </Card>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen
      title={a('registerCollege')}
      subtitle={a('registerCollegeSub')}
      footer={<AuthButton label={a('submitForReview')} icon="send-outline" onPress={submit} loading={busy} />}
    >
      {FIELDS.map(([k, label, cap]) => (
        <Field key={k} label={a(label as any)} value={form[k] || ''} onChangeText={set(k)} autoCapitalize={cap as any}
          keyboardType={k === 'official_email' ? 'email-address' : k === 'phone' ? 'phone-pad' : 'default'} />
      ))}
      <Field label={a('officerPassword')} value={password} onChangeText={setPassword} secure />
      <DocumentPicker label={a('authorizationDocument')} file={doc} onPicked={setDoc} onError={setError} />
      <Text style={accessStyles.muted}>{a('collegeReviewNote')}</Text>
      <ErrorText text={error} />
    </AuthScreen>
  );
}
