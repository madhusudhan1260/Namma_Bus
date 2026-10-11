import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text } from 'react-native';
import { useRouter } from 'expo-router';
import { COLORS } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { accessStyles, Card, Choice, ErrorText, Field, Loading, Row, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { DocumentPicker } from '../../components/access/DocumentPicker';
import { AccessApi, PickedFile } from '../../services/accessApi';

export default function StudentVerification() {
  const router = useRouter();
  const { ready } = useAccessGuard(['STUDENT']);
  const { a } = useAccessT();
  const [status, setStatus] = useState<any>(null);
  const [colleges, setColleges] = useState<{ code: string; name: string; city?: string }[]>([]);
  const [form, setForm] = useState<Record<string, string>>({
    college_code: '', student_name: '', college_email: '', student_id_number: '', course: '', branch: '', year: '', semester: '',
    phone: '', date_of_birth: '', pass_number: '', pass_issue_date: '', pass_expiry_date: '',
  });
  const [busPass, setBusPass] = useState<PickedFile | null>(null);
  const [idCard, setIdCard] = useState<PickedFile | null>(null);
  const [extra, setExtra] = useState<PickedFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    AccessApi.studentStatus().then(setStatus).catch(e => setError(e.message));
    AccessApi.colleges().then(r => setColleges(r.colleges)).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  const set = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    const required = ['college_code', 'student_name', 'student_id_number', 'phone', 'pass_expiry_date'];
    if (required.some(k => !form[k].trim())) return setError(a('fillRequired'));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.pass_expiry_date.trim())) return setError(a('errExpiryDate'));
    if (!busPass) return setError(a('uploadBusPass'));
    setBusy(true);
    setError(null);
    try {
      await AccessApi.submitStudent(form, { bus_pass: busPass, college_id_card: idCard || undefined, supporting_document: extra || undefined });
      setShowForm(false);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return (
      <AuthScreen title={a('studentPortalTitle')}>
        <ErrorText text={error} />
        <Loading />
      </AuthScreen>
    );
  }

  const canSubmit = ['NOT_SUBMITTED', 'REJECTED', 'EXPIRED'].includes(status.status);
  return (
    <AuthScreen title={a('studentPortalTitle')}>
      <Card title={a('studentStatusTitle')} right={<StatusBadge status={status.status} />}>
        {status.college ? <Row label={a('college')} value={status.college.name} /> : null}
        {status.pass?.pass_number ? <Row label={a('passNumber')} value={status.pass.pass_number} /> : null}
        {status.pass?.expiry_date ? <Row label={a('validUntil')} value={status.pass.expiry_date} /> : null}
        {status.rejection_reason ? <Text style={styles.reason}>{status.rejection_reason}</Text> : null}
        <Text style={accessStyles.muted}>
          {status.status === 'PENDING' ? a('studentPendingNote') : status.status === 'APPROVED' ? a('studentApprovedNote') : a('studentOtherNote')}
        </Text>
      </Card>

      {canSubmit && !showForm ? <AuthButton icon="cloud-upload-outline" label={a('submitStudentPass')} onPress={() => setShowForm(true)} /> : null}

      {showForm ? (
        <Card title={a('yourDetails')}>
          <Text style={accessStyles.muted}>{a('college')}</Text>
          {colleges.length ? (
            <Choice options={colleges.map(c => ({ value: c.code, label: c.city ? `${c.name} · ${c.city}` : c.name }))} value={form.college_code || null} onChange={set('college_code')} />
          ) : (
            <Notice tone="info" body={a('noColleges')} />
          )}
          <Field label={a('studentName')} value={form.student_name} onChangeText={set('student_name')} autoCapitalize="words" />
          <Field label={a('studentId')} value={form.student_id_number} onChangeText={set('student_id_number')} autoCapitalize="characters" />
          <Field label={a('phone')} value={form.phone} onChangeText={set('phone')} keyboardType="phone-pad" />
          <Field label={a('passExpiryDate')} value={form.pass_expiry_date} onChangeText={set('pass_expiry_date')} placeholder="YYYY-MM-DD" />
          <DocumentPicker label={a('busPassDocument')} file={busPass} onPicked={setBusPass} onError={setError} />
          <Text style={[accessStyles.muted, { marginTop: 8 }]}>{a('optionalDetails')}</Text>
          <Field label={a('collegeEmailOptional')} value={form.college_email} onChangeText={set('college_email')} keyboardType="email-address" />
          <Field label={a('course')} value={form.course} onChangeText={set('course')} autoCapitalize="words" />
          <Field label={a('branch')} value={form.branch} onChangeText={set('branch')} autoCapitalize="words" />
          <Field label={a('year')} value={form.year} onChangeText={set('year')} keyboardType="number-pad" />
          <Field label={a('semester')} value={form.semester} onChangeText={set('semester')} keyboardType="number-pad" />
          <Field label={a('dob')} value={form.date_of_birth} onChangeText={set('date_of_birth')} />
          <Field label={a('passNumberOptional')} value={form.pass_number} onChangeText={set('pass_number')} autoCapitalize="characters" />
          <Field label={a('passIssueDate')} value={form.pass_issue_date} onChangeText={set('pass_issue_date')} />
          <DocumentPicker label={a('collegeIdDocument')} file={idCard} onPicked={setIdCard} onError={setError} />
          <DocumentPicker label={a('extraDocument')} file={extra} onPicked={setExtra} onError={setError} />
          <Text style={accessStyles.muted}>{a('documentsPrivate')}</Text>
        </Card>
      ) : null}
      <ErrorText text={error} />
      {showForm ? <AuthButton icon="send-outline" label={a('submitForCollege')} onPress={submit} loading={busy} /> : null}
      <AuthButton variant="secondary" label={a('goToDashboard')} onPress={() => router.replace('/(tabs)' as any)} />
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  reason: { color: '#8E1C1C', marginVertical: 6, fontWeight: '600' },
  unused: { color: COLORS.textMuted },
});
