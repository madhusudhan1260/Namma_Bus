import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { AuthButton, Notice, useAuthStrings } from '../../components/auth/AuthUi';
import { ErrorText, Field } from '../../components/access/AccessUi';
import { HeroScene } from '../../components/home/HeroScene';
import { routeAfterLogin } from '../../components/access/routeAfterLogin';
import { ENTRY_EASING, isTransitionActive, runEntryTransition } from '../../components/access/transition';
import { useReducedMotion } from '../../components/access/useReducedMotion';
import { useAuth } from '../../context/AuthContext';
import { AccessApi, AccessError, AccessSession, EmailCodeChallenge, Portal } from '../../services/accessApi';

const native = Platform.OS !== 'web';
const ease = Easing.bezier(...ENTRY_EASING);
// Web-only CSS transition for hover/press feedback (ignored on native)
const webTransition: any = Platform.OS === 'web' ? { transitionProperty: 'transform, box-shadow, border-color, background-color', transitionDuration: '160ms' } : null;

const ROLES: { value: Portal; icon: keyof typeof Ionicons.glyphMap; name: string; desc: string }[] = [
  { value: 'passenger', icon: 'people-outline', name: 'portalPassenger', desc: 'rolePassengerDesc' },
  { value: 'conductor', icon: 'bus-outline', name: 'portalConductor', desc: 'roleConductorDesc' },
  { value: 'college', icon: 'school-outline', name: 'portalCollege', desc: 'roleCollegeDesc' },
  { value: 'admin', icon: 'shield-checkmark-outline', name: 'portalSuperAdmin', desc: 'roleAdminDesc' },
];

/** Decorative Bengaluru "route map": faint route lines and stop dots. Purely visual. */
function RouteBackdrop({ dark = false }: { dark?: boolean }) {
  const line = dark ? 'rgba(255,255,255,0.08)' : 'rgba(18,53,91,0.06)';
  const dot = dark ? 'rgba(255,255,255,0.22)' : 'rgba(18,53,91,0.12)';
  const lines = [
    { top: '18%', left: '-10%', width: '80%', rotate: '-12deg' },
    { top: '42%', left: '20%', width: '95%', rotate: '9deg' },
    { top: '70%', left: '-15%', width: '70%', rotate: '-4deg' },
    { top: '30%', left: '55%', width: '60%', rotate: '62deg' },
  ];
  const dots = [
    { top: '16%', left: '22%' }, { top: '40%', left: '48%' }, { top: '47%', left: '78%' },
    { top: '69%', left: '30%' }, { top: '24%', left: '70%' }, { top: '82%', left: '62%' },
  ];
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {lines.map((l, i) => (
        <View key={i} style={{ position: 'absolute', top: l.top as any, left: l.left as any, width: l.width as any, height: 3, borderRadius: 2,
          backgroundColor: line, transform: [{ rotate: l.rotate }] }} />
      ))}
      {dots.map((d, i) => (
        <View key={i} style={{ position: 'absolute', top: d.top as any, left: d.left as any, width: 9, height: 9, borderRadius: 5, borderWidth: 2,
          borderColor: dot, backgroundColor: dark ? 'transparent' : '#FFFFFF' }} />
      ))}
    </View>
  );
}

/** Friendly, honest messages for sign-in failures (server messages are kept when they are specific). */
function friendlyError(e: any, a: (k: any, v?: any) => string): string {
  if (e instanceof AccessError) {
    if (e.status === 0) return a('errNetwork');
    if (e.status === 408) return a('errTimeout');
    if (e.status >= 500) return a('errBackend');
    return e.message || a('signInFailed');
  }
  return a('signInFailed');
}

/** The single ನಮ್ಮ Bus sign-in for passengers, conductors, colleges and the Super Admin. */
export default function AccessLogin() {
  const router = useRouter();
  const { next } = useLocalSearchParams<{ next?: string }>();
  const { a } = useAccessT();
  const { lang, setLang, tr } = useAuthStrings();
  const { continueAsGuest } = useAuth();
  const { width, height } = useWindowDimensions();
  const [panelW, setPanelW] = useState(0);
  const reduced = useReducedMotion();
  const wide = width >= 960;
  const compactRoles = width < 520;

  const [portal, setPortal] = useState<Portal>('passenger');
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [collegeCode, setCollegeCode] = useState('');
  const [totp, setTotp] = useState('');
  const [needTotp, setNeedTotp] = useState(false);
  const [otpMode, setOtpMode] = useState(false);
  const [otpSent, setOtpSent] = useState<{ dev?: string; notice?: string } | null>(null);
  const [otp, setOtp] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [challenge, setChallenge] = useState<EmailCodeChallenge | null>(null);
  const [emailCode, setEmailCode] = useState('');
  const [resendIn, setResendIn] = useState(0);
  const [info, setInfo] = useState<string | null>(null);
  const inFlight = useRef(false);

  // Entrance (card fades/slides up) and exit (whole login panel slides LEFT) animations
  const enter = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const exit = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(enter, { toValue: 1, duration: reduced ? 0 : 520, easing: ease, useNativeDriver: native }).start();
  }, [enter, reduced]);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn(resendIn - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  const nextPath = typeof next === 'string' ? next : null;

  /** Called only after the server confirmed the sign-in. Plays the transition, then lands on the existing dashboard. */
  const enterSystem = (s: AccessSession) => {
    if (isTransitionActive()) return;
    setLeaving(true);
    Animated.timing(exit, { toValue: 1, duration: reduced ? 180 : 900, easing: ease, useNativeDriver: native }).start();
    runEntryTransition(() => routeAfterLogin(router, s, nextPath), reduced);
  };

  const guard = async (fn: () => Promise<void>) => {
    if (inFlight.current || leaving) return; // no duplicate requests / transitions
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e: any) {
      if (e instanceof AccessError && e.status === 401 && /Two-factor code required/i.test(e.message)) {
        setNeedTotp(true);
        setError(a('enterTwoFactor'));
      } else setError(friendlyError(e, a));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const submit = () =>
    guard(async () => {
      if (otpMode) {
        if (!otpSent) {
          const r = await AccessApi.otpRequest(identifier.trim());
          setOtpSent({ dev: r.development_otp, notice: r.development_notice });
        } else {
          enterSystem(await AccessApi.otpVerify(identifier.trim(), otp.trim()));
        }
        return;
      }
      if (!identifier.trim() || !password) {
        setError(a('errFillCredentials'));
        return;
      }
      if (portal === 'conductor') {
        enterSystem(await AccessApi.conductorLogin(identifier.trim().toUpperCase(), password, needTotp ? totp.trim() : undefined));
        return;
      }
      const r = await AccessApi.login({
        identifier: identifier.trim(),
        password,
        portal,
        college_code: portal === 'college' && collegeCode.trim() ? collegeCode.trim() : undefined,
        totp_code: needTotp ? totp.trim() : undefined,
      });
      if ('status' in r && r.status === 'EMAIL_CODE_SENT') {
        setChallenge(r);
        setEmailCode('');
        setInfo(null);
        setResendIn(r.resend_after);
        return;
      }
      enterSystem(r as AccessSession);
    });

  const verifyEmailCode = () =>
    guard(async () => {
      if (!challenge) return;
      try {
        enterSystem(await AccessApi.loginVerify(challenge.challenge_id, emailCode.trim()));
      } catch (e: any) {
        if (e instanceof AccessError && /expired|sign in again/i.test(e.message)) setChallenge(null);
        throw e;
      }
    });

  const resend = async () => {
    if (!challenge) return;
    setError(null);
    try {
      const r = await AccessApi.loginResend(challenge.challenge_id);
      setChallenge(r);
      setEmailCode('');
      setResendIn(r.resend_after);
      setInfo(a('codeResent'));
    } catch (e: any) {
      setError(friendlyError(e, a));
    }
  };

  const explore = async () => {
    await continueAsGuest();
    router.replace('/(tabs)' as any);
  };

  const choosePortal = (p: Portal) => {
    setPortal(p);
    setOtpMode(false);
    setOtpSent(null);
    setNeedTotp(false);
    setError(null);
    setIdentifier('');
    setPassword('');
  };

  const idLabel =
    portal === 'conductor' ? a('conductorIdLabel') : portal === 'college' ? a('officialCollegeEmail') : portal === 'admin' ? a('adminIdLabel') : a('mobileOrEmail');
  const submitLabel = busy ? a('signingIn') : otpMode ? (otpSent ? a('verifyCode') : a('sendCode')) : a('login');

  // ------------------------------------------------------------------ pieces
  const submitButton = (onPress: () => void, label: string, disabled = false) => (
    <Pressable
      onPress={onPress}
      disabled={busy || disabled || leaving}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: busy || disabled || leaving, busy }}
      style={(state: any) => [
        styles.submit,
        webTransition,
        state.hovered && !busy && styles.submitHover,
        state.pressed && { transform: [{ scale: 0.98 }] },
        (busy || disabled) && styles.submitDisabled,
      ]}
    >
      {busy ? <ActivityIndicator color="#FFFFFF" style={{ marginRight: 10 }} /> : <Ionicons name="log-in-outline" size={18} color="#FFFFFF" style={{ marginRight: 8 }} />}
      <Text style={styles.submitText}>{label}</Text>
    </Pressable>
  );

  const roleCards = (
    <View style={[styles.roles, compactRoles && styles.rolesStacked]} accessibilityRole="radiogroup" accessibilityLabel={a('continueAs')}>
      {ROLES.map(r => {
        const active = portal === r.value;
        return (
          <Pressable
            key={r.value}
            onPress={() => choosePortal(r.value)}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, checked: active }}
            accessibilityLabel={`${a(r.name as any)}. ${a(r.desc as any)}`}
            style={(state: any) => [
              styles.role,
              compactRoles ? styles.roleRow : styles.roleTile,
              webTransition,
              active && styles.roleActive,
              state.hovered && !active && styles.roleHover,
              state.focused && styles.focusRing,
              state.pressed && { transform: [{ scale: 0.98 }] },
            ]}
          >
            <View style={[styles.roleIcon, active && styles.roleIconActive]}>
              <Ionicons name={r.icon} size={20} color={active ? '#FFFFFF' : COLORS.deepNavy} />
            </View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={[styles.roleName, active && { color: COLORS.deepNavy }]} numberOfLines={1}>{a(r.name as any)}</Text>
              <Text style={styles.roleDesc} numberOfLines={2}>{a(r.desc as any)}</Text>
            </View>
            {active ? <Ionicons name="checkmark-circle" size={18} color={BMTC_ORANGE} /> : null}
          </Pressable>
        );
      })}
    </View>
  );

  const form = challenge ? (
    <>
      <Text style={styles.formTitle}>{a('checkEmail')}</Text>
      <Notice tone="info" body={a('codeSentTo', { email: challenge.email_hint, min: Math.round(challenge.expires_in / 60) })} />
      {challenge.development_code ? <Notice tone="demo" title={challenge.development_notice} body={`Development code: ${challenge.development_code}`} /> : null}
      <Field label={a('emailCode')} value={emailCode} onChangeText={v => setEmailCode(v.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" />
      {info ? <Text style={styles.info}>{info}</Text> : null}
      <ErrorText text={error} />
      {submitButton(verifyEmailCode, busy ? a('signingIn') : a('verify'), emailCode.trim().length !== 6)}
      <AuthButton variant="link" icon="refresh" label={resendIn > 0 ? a('resendIn', { s: resendIn }) : a('resendCode')} onPress={resend} disabled={resendIn > 0} />
      <Text style={styles.note}>{a('checkSpam')}</Text>
      <AuthButton variant="link" label={a('differentAccount')} onPress={() => { setChallenge(null); setError(null); setPassword(''); }} />
    </>
  ) : (
    <>
      <Text style={styles.caption}>{a('continueAs')}</Text>
      {roleCards}
      <Text style={styles.formTitle}>{a('signInAs', { role: a(ROLES.find(r => r.value === portal)!.name as any) })}</Text>
      {portal === 'college' ? (
        <Field label={a('collegeIdOptional')} value={collegeCode} onChangeText={setCollegeCode} autoCapitalize="characters" placeholder="DEMO-COLLEGE" />
      ) : null}
      <Field
        label={idLabel}
        value={identifier}
        onChangeText={setIdentifier}
        keyboardType={portal === 'conductor' ? 'default' : 'email-address'}
        autoCapitalize={portal === 'conductor' ? 'characters' : 'none'}
        placeholder={portal === 'conductor' ? 'CONDUCTOR-365P' : undefined}
      />
      {otpMode ? (
        otpSent ? (
          <>
            {otpSent.dev ? <Notice tone="demo" title={otpSent.notice} body={`Development code: ${otpSent.dev}`} /> : <Notice tone="info" body={a('codeSent')} />}
            <Field label={a('oneTimeCode')} value={otp} onChangeText={setOtp} keyboardType="number-pad" />
          </>
        ) : null
      ) : (
        <Field label={portal === 'conductor' ? a('passwordOrPin') : a('password')} value={password} onChangeText={setPassword} secure />
      )}
      {needTotp ? <Field label={a('twoFactorCode')} value={totp} onChangeText={setTotp} keyboardType="number-pad" /> : null}
      <ErrorText text={error} />
      {submitButton(submit, submitLabel)}

      {portal === 'passenger' || portal === 'college' ? (
        <AuthButton variant="link" icon="key-outline" label={a('forgotPassword')} onPress={() => router.push('/access/forgot' as any)} />
      ) : null}
      {portal === 'passenger' ? (
        <>
          <AuthButton variant="link" label={otpMode ? a('passwordInstead') : a('otpInstead')}
            onPress={() => { setOtpMode(!otpMode); setOtpSent(null); setError(null); }} />
          <View style={styles.divider} />
          <Text style={styles.caption}>{a('noAccount')}</Text>
          <AuthButton variant="secondary" label={a('createAccount')} icon="person-add-outline"
            onPress={() => router.push({ pathname: '/access/register', params: nextPath ? { next: nextPath } : {} } as any)} />
          <AuthButton variant="link" icon="map-outline" label={a('exploreGuest')} onPress={explore} />
        </>
      ) : null}
      {portal === 'college' ? (
        <>
          <View style={styles.divider} />
          <Text style={styles.caption}>{a('collegeNotRegistered')}</Text>
          <AuthButton variant="secondary" icon="business-outline" label={a('registerCollege')} onPress={() => router.push('/access/college-register' as any)} />
        </>
      ) : null}
      {portal === 'conductor' || portal === 'admin' ? <Text style={styles.note}>{a('staffNote')}</Text> : null}
    </>
  );

  const brand = (
    <View style={styles.brandRow}>
      <View style={styles.brandMark}>
        <Ionicons name="bus" size={18} color="#FFFFFF" />
      </View>
      <View>
        <Text style={styles.brandName}>ನಮ್ಮ BUS</Text>
        <Text style={styles.brandSub}>{a('loginTagline')}</Text>
      </View>
    </View>
  );

  const langToggle = (
    <Pressable
      onPress={() => setLang(lang === 'EN' ? 'KN' : 'EN')}
      accessibilityRole="button"
      accessibilityLabel={tr('authLanguageToggle')}
      style={(state: any) => [styles.lang, webTransition, state.hovered && styles.langHover, state.focused && styles.focusRing]}
    >
      <Ionicons name="language-outline" size={16} color={COLORS.deepNavy} style={{ marginRight: 6 }} />
      <Text style={styles.langText}>{tr('authLanguageToggle')}</Text>
    </Pressable>
  );

  const entryStyle = {
    opacity: enter,
    transform: [{ translateY: enter.interpolate({ inputRange: [0, 1], outputRange: [20, 0] }) }],
  };
  const exitStyle = {
    opacity: exit.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }),
    transform: [{ translateX: exit.interpolate({ inputRange: [0, 1], outputRange: [0, -width] }) }],
  };

  return (
    <View style={styles.page}>
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom', 'left', 'right']}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
          <Animated.View style={[{ flex: 1 }, exitStyle]} pointerEvents={leaving ? 'none' : 'auto'}>
            <ScrollView contentContainerStyle={[styles.scroll, wide && styles.scrollWide]} keyboardShouldPersistTaps="handled">
              {wide ? (
                // Desktop: the pink Bengaluru scene (same as Home) on the left, the sign-in card on the right
                <View style={[styles.heroPanel, { minHeight: Math.max(560, height - 40) }]} onLayout={e => setPanelW(e.nativeEvent.layout.width)}>
                  {panelW ? (
                    <HeroScene
                      height={Math.max(560, height - 40)}
                      sceneWidth={panelW}
                      subtitle={a('heroSubtitle')}
                      title={
                        <View style={{ alignItems: 'center' }}>
                          <Text style={styles.heroBrand} accessibilityRole="header"><Text style={{ color: '#FFFFFF' }}>ನಮ್ಮ </Text>BUS</Text>
                          <Text style={styles.heroWelcome}>{a('loginWelcome')}</Text>
                          <View style={styles.featureList}>
                            {(['featureLive', 'featureTickets', 'featurePasses'] as const).map(k => (
                              <View key={k} style={styles.feature}>
                                <Ionicons name="checkmark-circle" size={18} color="#FFFFFF" style={{ marginRight: 8 }} />
                                <Text style={styles.featureText}>{a(k)}</Text>
                              </View>
                            ))}
                          </View>
                        </View>
                      }
                    />
                  ) : null}
                </View>
              ) : (
                // Phone: the scene across the top, the sign-in card rising over its road
                <View style={{ width, marginBottom: -56 }}>
                  <HeroScene height={Math.round(Math.min(300, Math.max(240, height * 0.36)))} subtitle={a('heroSubtitle')} topRight={langToggle} />
                </View>
              )}

              <Animated.View style={[styles.card, wide ? styles.cardWide : { width: Math.min(520, width - 32) }, entryStyle]}>
                {wide ? (
                  <View style={styles.cardTop}>
                    <Text style={styles.cardTitle} accessibilityRole="header">{a('welcomeBack')}</Text>
                    {langToggle}
                  </View>
                ) : (
                  <Text style={[styles.cardTitle, { fontSize: 22 }]} accessibilityRole="header">{a('welcomeBack')}</Text>
                )}
                {form}
                <Text style={styles.powered}>{a('poweredBy')}</Text>
              </Animated.View>
            </ScrollView>
          </Animated.View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const BMTC_ORANGE = '#C2185B'; // accent (matches the pink Home theme)

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#FBF2F5', overflow: 'hidden' },
  scroll: { flexGrow: 1, paddingBottom: SPACING.xl, alignItems: 'center' },
  heroPanel: { flex: 1.05, borderRadius: 28, overflow: 'hidden', backgroundColor: '#B83574' },
  heroBrand: { color: '#7E1426', fontSize: 64, fontWeight: '900', letterSpacing: 2, textShadowColor: 'rgba(255,255,255,0.35)', textShadowRadius: 8, textShadowOffset: { width: 0, height: 2 } },
  heroWelcome: { color: '#FFFFFF', fontSize: 22, fontWeight: '900', textAlign: 'center', marginTop: 4 },
  featureList: { marginTop: 14, paddingHorizontal: 18, paddingVertical: 12, borderRadius: 16, backgroundColor: 'rgba(90, 10, 45, 0.35)' },
  scrollWide: { flexDirection: 'row', alignItems: 'stretch', padding: SPACING.xl, gap: SPACING.xl, maxWidth: 1200, alignSelf: 'center', width: '100%' },

  hero: { flex: 1.05, backgroundColor: COLORS.deepNavy, borderRadius: 28, padding: 40, overflow: 'hidden', justifyContent: 'space-between', minHeight: 560 },
  heroTitle: { color: '#FFFFFF', fontSize: 34, fontWeight: '900', lineHeight: 40, marginBottom: SPACING.sm },
  heroBody: { color: 'rgba(255,255,255,0.8)', fontSize: 16, marginBottom: SPACING.lg },
  feature: { flexDirection: 'row', alignItems: 'center', marginBottom: 10 },
  featureText: { color: '#FFFFFF', fontSize: 15, fontWeight: '600' },
  heroRoad: { alignItems: 'flex-end', marginTop: SPACING.xl },
  heroRoadLine: { height: 4, borderRadius: 2, alignSelf: 'stretch', marginTop: 10, backgroundColor: 'rgba(255,255,255,0.18)' },

  card: {
    width: '100%', maxWidth: 520, backgroundColor: '#FFFFFF', borderRadius: 24, padding: SPACING.lg,
    shadowColor: '#0B2545', shadowOpacity: 0.1, shadowRadius: 24, shadowOffset: { width: 0, height: 10 }, elevation: 4,
    borderWidth: 1, borderColor: 'rgba(18,53,91,0.06)',
  },
  cardWide: { flex: 1, maxWidth: 520, padding: 32, justifyContent: 'center' },
  cardTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.md },
  cardTitle: { fontSize: 26, fontWeight: '900', color: COLORS.deepNavy, marginBottom: SPACING.md },
  mobileHero: { marginBottom: SPACING.md },
  mobileTitle: { fontSize: 22, fontWeight: '900', color: COLORS.deepNavy, lineHeight: 28 },
  mobileBody: { fontSize: 14, color: COLORS.textSecondary, marginTop: 4 },

  brandRow: { flexDirection: 'row', alignItems: 'center' },
  brandMark: { width: 38, height: 38, borderRadius: 12, backgroundColor: COLORS.deepNavy, alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  brandName: { fontSize: 18, fontWeight: '900', color: COLORS.deepNavy, letterSpacing: 0.5 },
  brandSub: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '600' },

  lang: { flexDirection: 'row', alignItems: 'center', minHeight: 44, paddingHorizontal: 12, borderRadius: 22, backgroundColor: '#EEF2F7' },
  langHover: { backgroundColor: '#E2E9F2' },
  langText: { color: COLORS.deepNavy, fontWeight: '800', fontSize: 13 },

  caption: { fontSize: 13, fontWeight: '800', color: COLORS.textSecondary, marginBottom: SPACING.sm, marginTop: SPACING.xs },
  roles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: SPACING.md },
  rolesStacked: { flexDirection: 'column', flexWrap: 'nowrap' },
  role: { flexDirection: 'row', alignItems: 'center', borderWidth: 1.5, borderColor: '#E1E7EF', borderRadius: 16, padding: 12, backgroundColor: '#FFFFFF', minHeight: 64 },
  roleTile: { width: '48.5%' as any, minHeight: 78 },
  roleRow: { width: '100%', minHeight: 78 },
  roleHover: { transform: [{ translateY: -3 }], borderColor: '#C9D5E4', shadowColor: '#0B2545', shadowOpacity: 0.08, shadowRadius: 10, shadowOffset: { width: 0, height: 4 } },
  roleActive: { borderColor: BMTC_ORANGE, backgroundColor: '#FFF0F5' },
  roleIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  roleIconActive: { backgroundColor: BMTC_ORANGE },
  roleName: { fontWeight: '900', color: COLORS.textPrimary, fontSize: 14 },
  roleDesc: { color: COLORS.textSecondary, fontSize: 12, lineHeight: 16, marginTop: 2 },
  focusRing: { borderColor: COLORS.primary, shadowColor: COLORS.primary, shadowOpacity: 0.35, shadowRadius: 0, shadowOffset: { width: 0, height: 0 } },

  formTitle: { fontSize: 17, fontWeight: '900', color: COLORS.deepNavy, marginBottom: SPACING.sm },
  submit: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', minHeight: 52, borderRadius: 14, backgroundColor: '#A3245A',
    marginTop: SPACING.xs, marginBottom: SPACING.sm,
  },
  submitHover: { transform: [{ translateY: -1 }], shadowColor: '#0B2545', shadowOpacity: 0.2, shadowRadius: 12, shadowOffset: { width: 0, height: 6 } },
  submitDisabled: { opacity: 0.7 },
  submitText: { color: '#FFFFFF', fontWeight: '900', fontSize: 16, letterSpacing: 0.3 },
  divider: { height: 1, backgroundColor: '#E8EDF3', marginVertical: SPACING.md },
  note: { fontSize: 12, color: COLORS.textMuted, textAlign: 'center', marginTop: SPACING.sm, lineHeight: 18 },
  info: { color: '#0F5F30', fontWeight: '600', marginBottom: SPACING.sm },
  powered: { textAlign: 'center', color: COLORS.textMuted, fontSize: 12, marginTop: SPACING.md, width: '100%' },
});
