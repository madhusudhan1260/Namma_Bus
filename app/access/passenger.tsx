import React, { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { COLORS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, AuthScreen, Notice } from '../../components/auth/AuthUi';
import { Card, DevBanner, ErrorText, Field, Loading, OfflineBanner, Row, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { DocumentPicker } from '../../components/access/DocumentPicker';
import { DashboardError } from '../../components/access/DashboardError';
import { AccessApi, PickedFile } from '../../services/accessApi';
import { parseDob } from '../../components/access/dob';

const ELIGIBILITY_LABEL: Record<string, string> = {
  REGULAR_PAID: 'eligRegularPaid',
  STUDENT_FREE: 'eligStudentFree',
  FEMALE_IDENTITY_VERIFIED_FREE: 'eligFemaleFree',
};

/** Passenger / student account: category, verification, eligibility (decided by the server), tickets, profile, devices. */
export default function PassengerDashboard() {
  const router = useRouter();
  const { a } = useAccessT();
  const params = useLocalSearchParams<{ identity?: string }>();
  const { ready } = useAccessGuard(['PASSENGER', 'STUDENT']);
  const [me, setMe] = useState<any>(null);
  const [elig, setElig] = useState<any>(null);
  const [sessions, setSessions] = useState<any[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [dob, setDob] = useState('');
  const [photo, setPhoto] = useState<PickedFile | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    AccessApi.me().then(setMe).catch(e => setError(e.message));
    AccessApi.eligibility().then(setElig).catch(() => undefined);
  }, []);
  useFocusEffect(
    useCallback(() => {
      if (ready) load();
    }, [ready, load])
  );

  const startEdit = () => {
    setName(me.name || '');
    setDob(me.date_of_birth ? me.date_of_birth.split('-').reverse().join('-') : '');
    setEditing(true);
    setInfo(null);
  };

  const saveProfile = async () => {
    const iso = dob.trim() ? parseDob(dob) : null;
    if (dob.trim() && !iso) return setError(a('errDob'));
    setBusy(true);
    setError(null);
    try {
      await AccessApi.updateProfile({ name: name.trim(), ...(iso ? { date_of_birth: iso } : {}) });
      if (photo) await AccessApi.uploadPhoto(photo);
      setEditing(false);
      setPhoto(null);
      setInfo(a('profileSaved'));
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const loadSessions = () => AccessApi.sessions().then(r => setSessions(r.sessions)).catch(e => setError(e.message));
  const revoke = async (id: string) => {
    try {
      await AccessApi.revokeSession(id);
      loadSessions();
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (!me) {
    return (
      <AuthScreen title="ನಮ್ಮ Bus">
        {error ? <DashboardError detail={error} onRetry={() => { setError(null); load(); }} /> : <Loading />}
      </AuthScreen>
    );
  }
  const p = me.passenger || {};
  const isFemale = p.gender === 'FEMALE';
  const identityVerified = p.identity_status === 'VERIFIED';
  const free = elig && elig.eligibility !== 'REGULAR_PAID';

  return (
    <AuthScreen title={a('helloName', { name: me.name })} subtitle={me.role === 'STUDENT' ? a('roleStudent') : a('rolePassenger')}>
      {me.offline ? <OfflineBanner at={me.cached_at} /> : null}
      {params.identity === 'VERIFIED' ? <Notice tone="success" body={a('identityVerifiedOk')} /> : null}
      {params.identity === 'FAILED' ? <Notice tone="warning" body={a('noAadhaarMsg')} /> : null}
      {params.identity === 'UNAVAILABLE' ? <Notice tone="warning" body={a('identityUnavailableShort')} /> : null}
      {p.identity_is_development || elig?.identity_is_development ? <DevBanner /> : null}
      {info ? <Notice tone="success" body={info} /> : null}

      <Card title={a('yourEligibility')}>
        <View style={[styles.eligBox, { backgroundColor: free ? '#E3F6EA' : '#EEF0F4' }]}>
          <Text style={[styles.eligTitle, { color: free ? '#0F5F30' : COLORS.deepNavy }]}>
            {elig ? a((ELIGIBILITY_LABEL[elig.eligibility] || 'eligRegularPaid') as any) : '…'}
          </Text>
          {elig?.message ? <Text style={styles.note}>{elig.message}</Text> : null}
        </View>
        {me.passenger_category ? <Row label={a('passengerCategory')} value={me.passenger_category.replace(/_/g, ' ')} /> : null}
        {isFemale ? <Row label={a('identityVerificationLabel')} value={<StatusBadge status={p.identity_status} />} /> : null}
        {me.student ? <Row label={a('studentBusPass')} value={<StatusBadge status={me.student.status} />} /> : null}
        {me.student?.rejection_reason ? <Text style={styles.reason}>{a('reason')}: {me.student.rejection_reason}</Text> : null}
        {me.student?.pass_expiry_date ? <Row label={a('passValidUntil')} value={me.student.pass_expiry_date} /> : null}
        {elig?.eligibility_suspended ? <Notice tone="warning" body={a('eligSuspended')} /> : null}
        {elig?.reason_code === 'VERIFICATION_REQUIRED' || elig?.reason_code === 'VERIFICATION_EXPIRED' ? (
          <Text style={styles.note}>{a('completeVerification')}</Text>
        ) : null}
      </Card>

      <AuthButton icon="ticket-outline" label={a('buyTicket')} onPress={() => router.push('/access/buy' as any)} />
      {isFemale && p.has_aadhaar_answer !== false && !identityVerified ? (
        <AuthButton variant="secondary" icon="shield-checkmark-outline" label={a('verifyIdentity')} onPress={() => router.push('/access/aadhaar' as any)} />
      ) : null}
      {me.role === 'STUDENT' ? (
        <AuthButton variant="secondary" icon="school-outline" label={a('studentVerification')} onPress={() => router.push('/access/student' as any)} />
      ) : null}

      <Card title={a('recentTickets')}>
        {!elig?.recent_tickets?.length ? <Text style={styles.note}>{a('noTicketsYet')}</Text> : null}
        {(elig?.recent_tickets || []).map((t: any) => (
          <Row key={t.id} label={`${t.route} · ${new Date(t.created_at).toLocaleDateString()}`} value={`₹${t.fare} · ${t.status}`} />
        ))}
        <AuthButton variant="link" icon="list-outline" label={a('myTickets')} onPress={() => router.push('/access/tickets' as any)} />
      </Card>

      <Card title={a('profile')}>
        {editing ? (
          <>
            <Field label={a('fullName')} value={name} onChangeText={setName} autoCapitalize="words" />
            <Field label={a('dobLabel')} value={dob} onChangeText={setDob} placeholder="DD-MM-YYYY" />
            <DocumentPicker label={a('profilePhotoOptional')} file={photo} onPicked={setPhoto} onError={setError} />
            <Text style={styles.note}>{a('photoNote')}</Text>
            <AuthButton label={a('save')} icon="checkmark" onPress={saveProfile} loading={busy} />
            <AuthButton variant="link" label={a('cancel')} onPress={() => setEditing(false)} />
          </>
        ) : (
          <>
            <Row label={a('email')} value={me.email} />
            <Row label={a('mobile')} value={me.phone || '—'} />
            <Row label={a('dobLabel')} value={me.date_of_birth || '—'} />
            <Row label={a('profilePhoto')} value={me.has_profile_photo ? a('yes') : a('no')} />
            <AuthButton variant="link" icon="create-outline" label={a('editProfile')} onPress={startEdit} />
          </>
        )}
      </Card>

      <Card title={a('signedInDevices')}>
        {sessions === null ? (
          <AuthButton variant="link" icon="phone-portrait-outline" label={a('showDevices')} onPress={loadSessions} />
        ) : (
          sessions.map(s => (
            <View key={s.id} style={styles.session}>
              <Text style={styles.sessionText} numberOfLines={2}>
                {s.current ? `★ ${a('thisDevice')} · ` : ''}{s.device}
                {'\n'}
                <Text style={styles.note}>{new Date(s.last_used_at).toLocaleString()}</Text>
              </Text>
              {!s.current ? <AuthButton variant="link" label={a('signOutDevice')} onPress={() => revoke(s.id)} /> : null}
            </View>
          ))
        )}
      </Card>
      <ErrorText text={error} />

      <View style={styles.links}>
        <AuthButton variant="link" icon="map-outline" label={a('liveBuses')} onPress={() => router.push('/(tabs)/map' as any)} />
        <AuthButton variant="link" icon="help-circle-outline" label={a('helpFeedback')} onPress={() => router.push('/access/help' as any)} />
        <AuthButton variant="link" icon="lock-closed-outline" label={a('privacyAccount')} onPress={() => router.push('/access/privacy' as any)} />
        <AuthButton variant="link" icon="log-out-outline" label={a('signOut')} onPress={() => AccessApi.logout()} />
      </View>
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  reason: { color: '#8E1C1C', fontSize: 13, marginTop: 4 },
  note: { color: COLORS.textSecondary, fontSize: 13, marginTop: 4, lineHeight: 19 },
  links: { marginTop: SPACING.md },
  eligBox: { borderRadius: 12, padding: SPACING.md, marginBottom: SPACING.sm },
  eligTitle: { fontSize: 18, fontWeight: '900' },
  session: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  sessionText: { flex: 1, color: COLORS.textPrimary, fontSize: 13 },
});
