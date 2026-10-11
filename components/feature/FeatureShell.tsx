import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAccessT } from '../../constants/accessI18n';
import { useReducedMotion } from '../access/useReducedMotion';
import { PressScale } from '../ui/motion';

const native = Platform.OS !== 'web';
const EASE = Easing.bezier(0.22, 1, 0.36, 1);
export const PINK = '#D6455F';
export const MAGENTA = '#8E2470';
export const ACCENT = '#B1285F';
const BAR = ['#D6455F', '#CF4262', '#C73F65', '#BF3B67', '#B63869', '#AD346B', '#A4306C', '#9B2C6E', '#922870', '#8E2470'];

/** A pink→magenta horizontal gradient (drawn as soft columns; no gradient library needed). */
export function GradientFill({ style, radius = 0 }: { style?: any; radius?: number }) {
  if (Platform.OS === 'web') {
    // Smooth CSS gradient on the web
    return (
      <View pointerEvents="none"
        style={[StyleSheet.absoluteFill, { borderRadius: radius, backgroundImage: `linear-gradient(90deg, ${BAR[0]}, ${BAR[BAR.length - 1]})` } as any, style]} />
    );
  }
  return (
    <View style={[StyleSheet.absoluteFill, { flexDirection: 'row', borderRadius: radius, overflow: 'hidden' }, style]} pointerEvents="none">
      {BAR.map(c => <View key={c} style={{ flex: 1, backgroundColor: c }} />)}
    </View>
  );
}

/** Primary pink-gradient button used across the feature screens. */
export function GradientButton({ label, onPress, disabled, icon, busy }: { label: string; onPress: () => void; disabled?: boolean; icon?: keyof typeof Ionicons.glyphMap; busy?: boolean }) {
  return (
    <PressScale onPress={onPress} disabled={disabled || busy} style={[styles.gBtn, (disabled || busy) && { opacity: 0.6 }]} accessibilityRole="button" accessibilityLabel={label}
      accessibilityState={{ disabled: !!(disabled || busy), busy: !!busy }}>
      <GradientFill radius={14} />
      {icon ? <Ionicons name={icon} size={18} color="#FFFFFF" style={{ marginRight: 8 }} /> : null}
      <Text style={styles.gBtnText}>{label}</Text>
    </PressScale>
  );
}

type MapType = 'standard' | 'satellite';

/**
 * Feature screen layout: pink top bar (ನಮ್ಮ BUS · Helpline · Home), a map with a Map / Satellite switch, and a
 * white panel with the round ✕ tab. Laptop: panel on the right, slides in. Phone: map on top, panel as a sheet
 * below that slides up; ✕ tucks the panel away to show more map.
 */
export function FeatureShell({ title, icon, color, renderMap, aside, children, footer }: {
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  /** The map (receives the selected map type). Omit for screens without a map. */
  renderMap?: (mapType: MapType) => React.ReactNode;
  /** Shown instead of a map on wide screens when there is no map (e.g. an illustration) */
  aside?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const router = useRouter();
  const { a } = useAccessT();
  const { width, height } = useWindowDimensions();
  const reduced = useReducedMotion();
  const wide = width >= 900;
  const panelWidth = Math.min(460, Math.max(380, width * 0.32));
  const [mapType, setMapType] = useState<MapType>('standard');
  const [open, setOpen] = useState(true);

  const bar = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const panel = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    Animated.timing(bar, { toValue: 1, duration: reduced ? 0 : 420, easing: EASE, useNativeDriver: native }).start();
  }, [bar, reduced]);
  useEffect(() => {
    Animated.timing(panel, { toValue: open ? 1 : 0, duration: reduced ? 0 : 520, delay: open ? 120 : 0, easing: EASE, useNativeDriver: native }).start();
  }, [panel, open, reduced]);

  const panelTransform = wide
    ? [{ translateX: panel.interpolate({ inputRange: [0, 1], outputRange: [panelWidth, 0] }) }]
    : [{ translateY: panel.interpolate({ inputRange: [0, 1], outputRange: [height * 0.5, 0] }) }];
  const hasMap = !!renderMap;
  const mapHeightPhone = hasMap ? Math.max(220, Math.round(height * 0.36)) : 0;

  const mapArea = hasMap ? (
    <View style={[styles.map, !wide && { height: open ? mapHeightPhone : undefined, flex: open ? undefined : 1 }]}>
      {renderMap!(mapType)}
      <View style={styles.mapSwitch} accessibilityRole="radiogroup">
        {(['standard', 'satellite'] as const).map(t => (
          <Pressable key={t} onPress={() => setMapType(t)} accessibilityRole="radio" accessibilityState={{ selected: mapType === t }}
            style={[styles.mapSwitchBtn, mapType === t && styles.mapSwitchActive]}>
            <Text style={[styles.mapSwitchText, mapType === t && { color: '#111' }]}>{t === 'standard' ? a('fsMap') : a('fsSatellite')}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  ) : wide ? (
    <View style={[styles.map, styles.asideWrap]}>{aside}</View>
  ) : null;

  const closeTab = (
    <PressScale hoverLift={false} onPress={() => setOpen(o => !o)} style={[styles.tab, !wide && styles.tabPhone, { backgroundColor: ACCENT }]}
      accessibilityRole="button" accessibilityLabel={open ? a('fsHidePanel') : a('fsShowPanel')}>
      <Ionicons name={open ? 'close' : wide ? 'chevron-back' : 'chevron-up'} size={26} color="#FFFFFF" />
    </PressScale>
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <Animated.View style={[styles.bar, { opacity: bar, transform: [{ translateY: bar.interpolate({ inputRange: [0, 1], outputRange: [-20, 0] }) }] }]}>
        <GradientFill />
        <PressScale hoverLift={false} onPress={() => router.replace('/(tabs)' as any)} style={styles.brand} accessibilityRole="button" accessibilityLabel="ನಮ್ಮ BUS">
          <View style={styles.brandMark}><Ionicons name="bus" size={18} color={ACCENT} /></View>
          <Text style={styles.brandText}>ನಮ್ಮ BUS</Text>
        </PressScale>
        <View style={styles.barRight}>
          <PressScale hoverLift={false} onPress={() => router.push('/emergency' as any)} style={styles.helpline} accessibilityRole="button" accessibilityLabel={a('fsHelpline')}>
            <Ionicons name="call-outline" size={15} color="#FFFFFF" />
            <Text style={styles.helplineText}>{a('fsHelpline')}</Text>
          </PressScale>
          <PressScale hoverLift={false} onPress={() => router.replace('/(tabs)' as any)} style={styles.home} accessibilityRole="button" accessibilityLabel={a('fsHome')}>
            <Ionicons name="home-outline" size={24} color="#FFFFFF" />
          </PressScale>
        </View>
      </Animated.View>

      <View style={[styles.body, wide && { flexDirection: 'row' }]}>
        {mapArea}
        {wide ? (
          <Animated.View style={[styles.panelWide, { width: panelWidth, transform: panelTransform, marginRight: open ? 0 : -panelWidth }]}>
            {closeTab}
            <PanelContent title={title} icon={icon} color={color} footer={footer}>{children}</PanelContent>
          </Animated.View>
        ) : (
          <Animated.View style={[styles.panelPhone, open ? { flex: 1 } : { height: 64 }, { transform: panelTransform }]}>
            {closeTab}
            {open ? <PanelContent title={title} icon={icon} color={color} footer={footer}>{children}</PanelContent> : (
              <Pressable onPress={() => setOpen(true)} style={styles.peek} accessibilityRole="button" accessibilityLabel={a('fsShowPanel')}>
                <Ionicons name={icon} size={20} color={color} />
                <Text style={styles.peekTitle}>{title}</Text>
              </Pressable>
            )}
          </Animated.View>
        )}
      </View>
    </SafeAreaView>
  );
}

function PanelContent({ title, icon, color, children, footer }: { title: string; icon: keyof typeof Ionicons.glyphMap; color: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.panelBody} keyboardShouldPersistTaps="handled">
        <View style={styles.titleRow}>
          <View style={[styles.titleIcon, { backgroundColor: `${color}1F` }]}><Ionicons name={icon} size={20} color={color} /></View>
          <Text style={styles.title} accessibilityRole="header">{title}</Text>
        </View>
        {children}
      </ScrollView>
      {footer}
    </>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: PINK },
  bar: { height: 64, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, overflow: 'hidden' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  brandMark: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  brandText: { color: '#FFFFFF', fontWeight: '900', fontSize: 18, letterSpacing: 1 },
  barRight: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  helpline: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.85)' },
  helplineText: { color: '#FFFFFF', fontWeight: '800', fontSize: 14 },
  home: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, backgroundColor: '#F6F7F9', overflow: 'hidden' },
  map: { flex: 1, minHeight: 200, overflow: 'hidden' },
  asideWrap: { alignItems: 'center', justifyContent: 'center', backgroundColor: '#FBF4F7' },
  mapSwitch: { position: 'absolute', top: 12, left: 12, flexDirection: 'row', backgroundColor: '#FFFFFF', borderRadius: 4, overflow: 'hidden',
    shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, zIndex: 500, elevation: 4 },
  mapSwitchBtn: { paddingHorizontal: 16, minHeight: 40, justifyContent: 'center' },
  mapSwitchActive: { backgroundColor: '#FFFFFF' },
  mapSwitchText: { fontSize: 15, fontWeight: '600', color: '#666' },
  panelWide: { backgroundColor: '#FFFFFF', borderLeftWidth: 1, borderLeftColor: '#ECECEC', zIndex: 10 },
  panelPhone: { backgroundColor: '#FFFFFF', borderTopLeftRadius: 22, borderTopRightRadius: 22, marginTop: -18, zIndex: 10,
    shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 12, shadowOffset: { width: 0, height: -3 }, elevation: 8 },
  tab: { position: 'absolute', left: -34, top: 26, width: 64, height: 64, borderRadius: 32, alignItems: 'center', justifyContent: 'center', zIndex: 20,
    shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 6 },
  tabPhone: { left: 'auto' as any, right: 14, top: -26, width: 50, height: 50, borderRadius: 25 },
  peek: { flexDirection: 'row', alignItems: 'center', gap: 10, height: 64, paddingHorizontal: 20 },
  peekTitle: { fontSize: 17, fontWeight: '900', color: '#222' },
  panelBody: { padding: 22, paddingTop: 22, paddingBottom: 32 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 18, paddingRight: 40 },
  titleIcon: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: '800', color: '#1E1E24' },
  gBtn: { minHeight: 54, borderRadius: 14, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', overflow: 'hidden', marginTop: 6 },
  gBtnText: { color: '#FFFFFF', fontWeight: '800', fontSize: 16 },
});
