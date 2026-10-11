import React from 'react';
import {
  ActivityIndicator,
  Animated,
  KeyboardAvoidingView,
  KeyboardTypeOptions,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { t, TranslationKey } from '../../constants/i18n';
import { useTransit } from '../../context/TransitContext';
import { NotificationBell } from '../access/NotificationBell';

/** Translation helper bound to the commuter's preferred language. */
export function useAuthStrings() {
  const { preferredLanguage, setPreferredLanguage } = useTransit();
  const tr = React.useCallback((key: TranslationKey) => t(key, preferredLanguage), [preferredLanguage]);
  return { tr, lang: preferredLanguage, setLang: setPreferredLanguage };
}

// ---------------------------------------------------------------------------
// Client-side validation (mirrors backend/app/models/auth.py)
// ---------------------------------------------------------------------------

export function normalizeIndianMobile(raw: string): string | null {
  let digits = raw.replace(/[\s\-()]/g, '');
  if (digits.startsWith('+91')) digits = digits.slice(3);
  else if (digits.startsWith('91') && digits.length === 12) digits = digits.slice(2);
  else if (digits.startsWith('0') && digits.length === 11) digits = digits.slice(1);
  return /^[6-9]\d{9}$/.test(digits) ? digits : null;
}

export function isValidEmail(raw: string): boolean {
  const email = raw.trim();
  return email.length <= 254 && /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/.test(email);
}

export function isValidName(raw: string): boolean {
  const name = raw.trim().replace(/\s+/g, ' ');
  return name.length >= 2 && name.length <= 80 && /^[^\d<>{}[\]@#$%^*=_|\\/~`]+$/.test(name);
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

interface AuthScreenProps {
  title?: string;
  subtitle?: string;
  showBack?: boolean;
  children: React.ReactNode;
  /** Wider content column for staff/back-office screens on laptops (default: comfortable reading width) */
  wide?: boolean;
  /** Action area pinned to the bottom of the screen (stays visible while the content scrolls) */
  footer?: React.ReactNode;
  /** Desktop (≥ 1024 px): navigation shown in a left sidebar */
  sidebar?: React.ReactNode;
  /** Phones/tablets: navigation shown as a bottom bar (hidden when the sidebar is shown) */
  bottomBar?: React.ReactNode;
}

export function AuthScreen({ title, subtitle, showBack = true, children, wide, footer, sidebar, bottomBar }: AuthScreenProps) {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const desktop = !!sidebar && width >= 1024;
  const { tr, lang, setLang } = useAuthStrings();

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <View style={styles.topBar}>
          {showBack ? (
            <TouchableOpacity
              onPress={() => (router.canGoBack() ? router.back() : router.replace('/access' as any))}
              style={styles.iconButton}
              accessibilityRole="button"
              accessibilityLabel={tr('authBack')}
            >
              <Ionicons name="chevron-back" size={24} color={COLORS.deepNavy} />
            </TouchableOpacity>
          ) : (
            <View style={styles.iconButton} />
          )}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <TouchableOpacity
            onPress={() => setLang(lang === 'EN' ? 'KN' : 'EN')}
            style={styles.langButton}
            accessibilityRole="button"
            accessibilityLabel={tr('authLanguageToggle')}
            accessibilityHint={tr('authLanguageToggleHint')}
          >
            <Ionicons name="language-outline" size={18} color={COLORS.deepNavy} style={{ marginRight: 6 }} />
            <Text style={styles.langText}>{tr('authLanguageToggle')}</Text>
          </TouchableOpacity>
          <NotificationBell background="transparent" />
          </View>
        </View>
        <View style={{ flex: 1, flexDirection: 'row' }}>
        {desktop ? <View style={styles.sidebar}>{sidebar}</View> : null}
        <ScrollView style={{ flex: 1 }} contentContainerStyle={[styles.scroll, wide || desktop ? styles.scrollWide : null]} keyboardShouldPersistTaps="handled">
          {title ? (
            <Text style={styles.title} accessibilityRole="header">
              {title}
            </Text>
          ) : null}
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          {children}
        </ScrollView>
        </View>
        {!desktop && bottomBar ? <View style={styles.bottomBar}>{bottomBar}</View> : null}
        {footer ? (
          <View style={styles.footer}>
            <View style={[styles.footerInner, wide ? styles.scrollWide : null]}>{footer}</View>
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

interface AuthButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'link';
  disabled?: boolean;
  loading?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  accessibilityHint?: string;
}

export function AuthButton({ label, onPress, variant = 'primary', disabled, loading, icon, accessibilityHint }: AuthButtonProps) {
  const isPrimary = variant === 'primary';
  const isLink = variant === 'link';
  const color = isPrimary ? COLORS.textInverse : COLORS.primaryDark;
  const scale = React.useRef(new Animated.Value(1)).current;
  const press = (to: number) => Animated.spring(scale, { toValue: to, speed: 40, bounciness: 5, useNativeDriver: Platform.OS !== 'web' }).start();
  return (
    <Animated.View style={{ transform: [{ scale }] }}>
    <TouchableOpacity
      onPress={onPress}
      onPressIn={() => !isLink && press(0.97)}
      onPressOut={() => press(1)}
      disabled={disabled || loading}
      activeOpacity={0.85}
      style={[
        styles.button,
        isPrimary && styles.buttonPrimary,
        variant === 'secondary' && styles.buttonSecondary,
        isLink && styles.buttonLink,
        (disabled || loading) && styles.buttonDisabled,
      ]}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
    >
      {loading ? (
        <ActivityIndicator color={color} />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={color} style={{ marginRight: 8 }} /> : null}
          <Text style={[styles.buttonText, { color }, isLink && styles.buttonLinkText]}>{label}</Text>
        </>
      )}
    </TouchableOpacity>
    </Animated.View>
  );
}

interface AuthTextFieldProps {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  error?: string;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: 'none' | 'words';
  autoComplete?: 'name' | 'tel' | 'email';
  textContentType?: 'name' | 'telephoneNumber' | 'emailAddress';
}

export function AuthTextField({ label, value, onChangeText, placeholder, error, keyboardType, autoCapitalize = 'none', autoComplete, textContentType }: AuthTextFieldProps) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={COLORS.textMuted}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        autoComplete={autoComplete}
        textContentType={textContentType}
        style={[styles.input, error ? styles.inputError : null]}
        accessibilityLabel={label}
        accessibilityHint={error}
      />
      {error ? (
        <View style={styles.errorRow} accessibilityLiveRegion="polite">
          <Ionicons name="alert-circle" size={14} color={COLORS.error} style={{ marginRight: 4 }} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}
    </View>
  );
}

const NOTICE_TONES = {
  info: { bg: COLORS.infoBg, fg: COLORS.deepNavy, icon: 'information-circle' as const },
  warning: { bg: COLORS.warningBg, fg: '#7A4B00', icon: 'warning' as const },
  success: { bg: COLORS.successBg, fg: '#0F5F30', icon: 'checkmark-circle' as const },
  error: { bg: COLORS.errorBg, fg: '#8E1C1C', icon: 'close-circle' as const },
  demo: { bg: '#FFF4DB', fg: '#7A4B00', icon: 'flask' as const },
};

export function Notice({ tone = 'info', title, body }: { tone?: keyof typeof NOTICE_TONES; title?: string; body?: string }) {
  const c = NOTICE_TONES[tone];
  return (
    <View style={[styles.notice, { backgroundColor: c.bg }]} accessible accessibilityLabel={[title, body].filter(Boolean).join('. ')}>
      <Ionicons name={c.icon} size={20} color={c.fg} style={{ marginRight: 10, marginTop: 1 }} />
      <View style={{ flex: 1 }}>
        {title ? <Text style={[styles.noticeTitle, { color: c.fg }]}>{title}</Text> : null}
        {body ? <Text style={[styles.noticeBody, { color: c.fg }]}>{body}</Text> : null}
      </View>
    </View>
  );
}

export function StepLabel({ text }: { text: string }) {
  return <Text style={styles.stepLabel}>{text}</Text>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: COLORS.background },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.xs,
  },
  iconButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  langButton: {
    minHeight: 44,
    minWidth: 44,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.full,
    backgroundColor: COLORS.lightBlue,
  },
  langText: { color: COLORS.deepNavy, fontWeight: '700', fontSize: 14 },
  scroll: { padding: SPACING.xl, paddingBottom: SPACING.xxxl * 2, width: '100%', maxWidth: 640, alignSelf: 'center' },
  scrollWide: { maxWidth: 1180 },
  sidebar: { width: 248, borderRightWidth: 1, borderRightColor: COLORS.border, backgroundColor: COLORS.surface, paddingVertical: SPACING.md },
  bottomBar: { borderTopWidth: 1, borderTopColor: COLORS.border, backgroundColor: COLORS.surface },
  footer: { borderTopWidth: 1, borderTopColor: COLORS.border, backgroundColor: COLORS.surface, paddingHorizontal: SPACING.xl, paddingTop: SPACING.sm, paddingBottom: SPACING.md },
  footerInner: { width: '100%', maxWidth: 640, alignSelf: 'center' },
  title: { fontSize: 26, fontWeight: '800', color: COLORS.deepNavy, marginBottom: SPACING.xs },
  subtitle: { fontSize: 15, color: COLORS.textSecondary, marginBottom: SPACING.xl, lineHeight: 21 },
  button: {
    minHeight: 52,
    borderRadius: RADIUS.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACING.lg,
    marginTop: SPACING.md,
  },
  buttonPrimary: { backgroundColor: COLORS.deepNavy },
  buttonSecondary: { backgroundColor: COLORS.surface, borderWidth: 1.5, borderColor: COLORS.primary },
  buttonLink: { minHeight: 44, marginTop: SPACING.sm },
  buttonLinkText: { textDecorationLine: 'underline', fontWeight: '600' },
  buttonDisabled: { opacity: 0.55 },
  buttonText: { fontSize: 16, fontWeight: '700' },
  field: { marginBottom: SPACING.lg },
  fieldLabel: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 6 },
  input: {
    minHeight: 50,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    fontSize: 16,
    color: COLORS.textPrimary,
  },
  inputError: { borderColor: COLORS.error },
  errorRow: { flexDirection: 'row', alignItems: 'center', marginTop: 6 },
  errorText: { color: COLORS.error, fontSize: 13, flex: 1 },
  notice: { flexDirection: 'row', borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.lg },
  noticeTitle: { fontSize: 14, fontWeight: '800', marginBottom: 2 },
  noticeBody: { fontSize: 13, lineHeight: 19 },
  stepLabel: {
    fontSize: 12,
    fontWeight: '800',
    color: COLORS.primaryDark,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    marginBottom: SPACING.sm,
  },
});
