import React, { useCallback, useEffect, useState } from 'react';
import { Linking, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, useWindowDimensions, View } from 'react-native';
import { useAccessT } from '../../constants/accessI18n';
import { BottomNav, NavItem, SideNav } from '../../components/access/PortalNav';
import { COLORS, SPACING } from '../../constants/theme';
import { AuthButton, AuthScreen } from '../../components/auth/AuthUi';
import { accessStyles, Card, Choice, ErrorText, Field, Loading, Row, Stat, StatusBadge, useAccessGuard } from '../../components/access/AccessUi';
import { AccessApi } from '../../services/accessApi';
import { DashboardError } from '../../components/access/DashboardError';

const FILTERS = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'EXPIRED', label: 'Expired' },
  { value: 'REVOKED', label: 'Revoked' },
  { value: '', label: 'All' },
];

function openDocument(relative: string) {
  const url = AccessApi.documentUrl(relative);
  if (Platform.OS === 'web') window.open(url, '_blank', 'noopener');
  else Linking.openURL(url);
}

export default function CollegePortal() {
  const { ready } = useAccessGuard(['COLLEGE_ADMIN']);
  const wideLayout = useWindowDimensions().width >= 900;
  const [dash, setDash] = useState<any>(null);
  const [filter, setFilter] = useState('PENDING');
  const [query, setQuery] = useState('');
  const [revoking, setRevoking] = useState(false);
  const [list, setList] = useState<any[] | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [expiry, setExpiry] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { a } = useAccessT();
  const { width } = useWindowDimensions();
  const [section, setSection] = useState<'dashboard' | 'students' | 'passes' | 'profile'>('dashboard');
  const [pending, setPending] = useState<any[] | null>(null);
  useEffect(() => {
    if (ready && section === 'dashboard') AccessApi.collegeStudents('PENDING').then(r => setPending(r.students)).catch(() => setPending([]));
  }, [ready, section, dash]);
  const goSection = (k: 'dashboard' | 'students' | 'passes' | 'profile') => {
    setSection(k);
    if (k === 'passes') setFilter('APPROVED');
    if (k === 'students') setFilter('');
  };

  const load = useCallback(() => {
    AccessApi.collegeDashboard().then(setDash).catch(e => setError(e.message));
    AccessApi.collegeStudents(filter || undefined, query.trim() || undefined).then(r => setList(r.students)).catch(e => setError(e.message));
  }, [filter, query]);
  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(load, 250); // debounce typing in the search box
    return () => clearTimeout(t);
  }, [ready, load]);

  const open = async (id: string) => {
    setError(null);
    setRejecting(false);
    setRevoking(false);
    setReason('');
    try {
      const d = await AccessApi.collegeStudent(id);
      setDetail(d);
      setExpiry(d.pass_expiry_date || '');
    } catch (e: any) {
      setError(e.message);
    }
  };

  const act = async (kind: 'approve' | 'reject' | 'revoke') => {
    setBusy(true);
    setError(null);
    try {
      const d =
        kind === 'approve' ? await AccessApi.approve(detail.id, expiry || undefined)
          : kind === 'reject' ? await AccessApi.reject(detail.id, reason.trim())
            : await AccessApi.revokePass(detail.id, reason.trim());
      setDetail(d);
      setRejecting(false);
      setRevoking(false);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!dash) {
    return (
      <AuthScreen title="College Dashboard" showBack={false} wide>
        {error ? <DashboardError detail={error} onRetry={() => { setError(null); load(); }} /> : <Loading />}
      </AuthScreen>
    );
  }

  if (detail) {
    return (
      <AuthScreen title="Student Verification" wide>
        <View style={wideLayout ? styles.columns : undefined}>
        <View style={wideLayout ? styles.col : undefined}>
        <Card title={detail.student_name} right={<StatusBadge status={detail.status} />}>
          <Row label="Student ID" value={detail.student_id_number} />
          <Row label="Course" value={detail.course} />
          <Row label="Branch" value={detail.branch} />
          <Row label="Year / Semester" value={`${detail.year ?? '—'} / ${detail.semester ?? '—'}`} />
          <Row label="College" value={detail.college?.name} />
          <Row label="College email" value={detail.college_email} />
          <Row label="Pass number" value={detail.pass_number || '—'} />
          <Row label="Pass validity" value={`${detail.pass_issue_date || '—'} → ${detail.pass_expiry_date || '—'}`} />
          {detail.rejection_reason ? <Text style={styles.reason}>Rejected: {detail.rejection_reason}</Text> : null}
        </Card>
        <Card title="Uploaded documents">
          {[['Uploaded College ID', detail.college_id_document], ['Uploaded Bus Pass', detail.bus_pass_document], ['Additional document', detail.supporting_document]]
            .filter(([, d]) => d)
            .map(([label, d]: any) => (
              <TouchableOpacity key={d.id} style={styles.doc} onPress={() => openDocument(d.view_url)} accessibilityRole="link" accessibilityLabel={`Open ${label}`}>
                <Text style={styles.docLabel}>{label}</Text>
                <Text style={styles.docMeta}>{d.mime_type} · {Math.round(d.size_bytes / 1024)} KB · scan: {d.scan_status}</Text>
              </TouchableOpacity>
            ))}
          <Text style={accessStyles.muted}>Links are private and expire after a few minutes.</Text>
        </Card>
        </View>
        <View style={wideLayout ? styles.col : undefined}>
        {detail.status === 'PENDING' ? (
          <Card title="Decision">
            <Field label="Confirm pass valid until (YYYY-MM-DD)" value={expiry} onChangeText={setExpiry} />
            <ErrorText text={error} />
            {!rejecting ? (
              <>
                <AuthButton icon="checkmark-circle-outline" label="APPROVE" onPress={() => act('approve')} loading={busy} />
                <AuthButton variant="secondary" icon="close-circle-outline" label="REJECT" onPress={() => setRejecting(true)} />
              </>
            ) : (
              <>
                <Field label="Reason" value={reason} onChangeText={setReason} multiline />
                <AuthButton icon="close-circle-outline" label="CONFIRM REJECTION" onPress={() => act('reject')} loading={busy} disabled={reason.trim().length < 5} />
                <AuthButton variant="link" label="Cancel" onPress={() => setRejecting(false)} />
              </>
            )}
          </Card>
        ) : null}
        {detail.status === 'APPROVED' ? (
          <Card title="Withdraw pass">
            <Text style={accessStyles.muted}>Revoke if the student has left the college or the pass is no longer valid. Free tickets stop immediately.</Text>
            <ErrorText text={error} />
            {!revoking ? (
              <AuthButton variant="secondary" icon="ban-outline" label="REVOKE PASS" onPress={() => setRevoking(true)} />
            ) : (
              <>
                <Field label="Reason" value={reason} onChangeText={setReason} multiline />
                <AuthButton icon="ban-outline" label="CONFIRM REVOKE" onPress={() => act('revoke')} loading={busy} disabled={reason.trim().length < 5} />
                <AuthButton variant="link" label="Cancel" onPress={() => setRevoking(false)} />
              </>
            )}
          </Card>
        ) : null}
        </View>
        </View>
        <AuthButton variant="secondary" label="BACK TO LIST" onPress={() => setDetail(null)} />
      </AuthScreen>
    );
  }

  const nav: NavItem<'dashboard' | 'students' | 'passes' | 'profile'>[] = [
    { key: 'dashboard', icon: 'grid-outline', label: a('clDashboard'), badge: dash.pending || undefined },
    { key: 'students', icon: 'people-outline', label: a('clStudents') },
    { key: 'passes', icon: 'card-outline', label: a('clPasses') },
    { key: 'profile', icon: 'person-outline', label: a('clProfile') },
  ];
  const table = (rows: any[]) =>
    width >= 760 ? (
      <ScrollView horizontal>
        <View>
          <View style={[styles.tr, styles.th]}>
            {[a('colName'), a('colStudentId'), a('colPassNo'), a('colExpiry'), a('colStatus')].map(c => <Text key={c} style={[styles.td, styles.thText]}>{c}</Text>)}
          </View>
          {rows.map((r, i) => (
            <TouchableOpacity key={r.id} style={[styles.tr, i % 2 ? styles.trAlt : null]} onPress={() => open(r.id)} accessibilityRole="button" accessibilityLabel={`${r.student_name} ${r.status}`}>
              <Text style={[styles.td, { fontWeight: '800' }]} numberOfLines={1}>{r.student_name}</Text>
              <Text style={styles.td} numberOfLines={1}>{r.student_id_number || '—'}</Text>
              <Text style={styles.td} numberOfLines={1}>{r.pass_number || '—'}</Text>
              <Text style={styles.td} numberOfLines={1}>{r.pass_expiry_date || '—'}</Text>
              <View style={styles.td}><StatusBadge status={r.status} /></View>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    ) : (
      <>
        {rows.map(r => (
          <TouchableOpacity key={r.id} style={styles.item} onPress={() => open(r.id)} accessibilityRole="button" accessibilityLabel={`${r.student_name} ${r.status}`}>
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>{r.student_name}</Text>
              <Text style={styles.itemMeta}>{r.student_id_number} · {r.pass_number || '—'} · {r.pass_expiry_date || '—'}</Text>
            </View>
            <StatusBadge status={r.status} />
          </TouchableOpacity>
        ))}
      </>
    );

  const listCard = (title: string, filters: typeof FILTERS) => (
    <Card title={title}>
      <Field label="Search name, student ID or pass number" value={query} onChangeText={setQuery} />
      <Choice options={filters} value={filter} onChange={setFilter} />
      {!list ? <Loading /> : null}
      {list && list.length === 0 ? <Text style={accessStyles.muted}>No students in this list.</Text> : null}
      {list ? table(list) : null}
    </Card>
  );

  return (
    <AuthScreen title="COLLEGE DASHBOARD" subtitle={dash.college?.name} showBack={false} wide
      sidebar={<SideNav items={nav} active={section} onSelect={goSection} title={dash.college?.code} />}
      bottomBar={<BottomNav items={nav} active={section} onSelect={goSection} />}>
      {section === 'dashboard' ? (
        <>
          <View style={styles.stats}>
            <Stat label="Students" value={dash.students} />
            <Stat label="Pending" value={dash.pending} />
            <Stat label="Approved" value={dash.approved} />
            <Stat label="Rejected" value={dash.rejected} />
            <Stat label="Active passes" value={dash.active_passes} />
            <Stat label="Expired passes" value={dash.expired_passes} />
          </View>
          <Card title={`Pending verification (${dash.pending})`}>
            {pending === null ? <Loading /> : pending.length === 0 ? <Text style={accessStyles.muted}>No applications are waiting.</Text> : null}
            {(pending || []).map(p => (
              <View key={p.id} style={styles.pendingCard}>
                <Row label="Student" value={p.student_name} />
                <Row label="Student ID" value={p.student_id_number || '—'} />
                <Row label="Course" value={[p.course, p.branch].filter(Boolean).join(' · ') || '—'} />
                <Row label="Year" value={p.year ? String(p.year) : '—'} />
                <Row label="Pass expiry" value={p.pass_expiry_date || '—'} />
                <AuthButton icon="document-text-outline" label="VIEW DOCUMENTS & DECIDE" onPress={() => open(p.id)} />
              </View>
            ))}
          </Card>
        </>
      ) : section === 'students' ? (
        listCard('Students', FILTERS)
      ) : section === 'passes' ? (
        listCard('Bus passes', FILTERS.filter(f => ['APPROVED', 'EXPIRED', 'REVOKED'].includes(f.value)))
      ) : (
        <Card title={dash.college?.name || 'College'}>
          <Row label="Code" value={dash.college?.code || '—'} />
          <Row label="Status" value={dash.college?.status ? <StatusBadge status={dash.college.status} /> : '—'} />
          <AuthButton variant="link" icon="log-out-outline" label="Sign out" onPress={() => AccessApi.logout()} />
        </Card>
      )}
      <ErrorText text={error} />
    </AuthScreen>
  );
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.sm, marginBottom: SPACING.md },
  pendingCard: { borderWidth: 1, borderColor: COLORS.border, borderRadius: 14, padding: SPACING.md, marginBottom: SPACING.sm },
  tr: { flexDirection: 'row', alignItems: 'center', minHeight: 48, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  trAlt: { backgroundColor: '#F8FAFC' },
  th: { backgroundColor: COLORS.surfaceSubtle },
  td: { width: 170, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: COLORS.textPrimary },
  thText: { fontWeight: '900', color: COLORS.deepNavy },
  columns: { flexDirection: 'row', gap: SPACING.md, alignItems: 'flex-start' },
  col: { flex: 1 },
  item: { flexDirection: 'row', alignItems: 'center', minHeight: 56, borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle, gap: SPACING.sm },
  itemTitle: { fontWeight: '800', color: COLORS.textPrimary },
  itemMeta: { fontSize: 12, color: COLORS.textSecondary },
  reason: { color: '#8E1C1C', marginTop: 6 },
  doc: { minHeight: 48, justifyContent: 'center', borderBottomWidth: 1, borderBottomColor: COLORS.borderSubtle },
  docLabel: { fontWeight: '800', color: COLORS.primaryDark },
  docMeta: { fontSize: 12, color: COLORS.textSecondary },
});
