import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { NetworkApi } from '../../services/networkApi';
import { NetworkStop } from '../../types/network';
import { FadeIn, PressScale, stagger } from '../ui/motion';

const native = Platform.OS !== 'web';
const TEAL = '#1FC79A';

/** Outlined text field with a floating label (as in the reference design). */
export function OutlinedInput({ label, value, onChangeText, placeholder, onSubmit, autoFocus, autoCapitalize = 'none', inputRef, right, onBlur }: {
  label?: string; value: string; onChangeText: (v: string) => void; placeholder?: string; onSubmit?: () => void; autoFocus?: boolean;
  autoCapitalize?: 'none' | 'characters' | 'words'; inputRef?: React.RefObject<TextInput | null>; right?: React.ReactNode; onBlur?: () => void;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={[styles.outline, focused && styles.outlineFocused]}>
      {label && (value || focused) ? <Text style={styles.floating}>{label}</Text> : null}
      <TextInput
        ref={inputRef as any}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder || label}
        placeholderTextColor="#7A7D85"
        style={styles.input}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => { setFocused(false); onBlur?.(); }, 180)}
        onSubmitEditing={onSubmit}
        returnKeyType={onSubmit ? 'search' : 'next'}
        autoFocus={autoFocus}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        accessibilityLabel={label || placeholder}
      />
      {right}
    </View>
  );
}

/** A place field that suggests real BMTC stops as you type. */
function StopField({ label, value, onChange, onPick, inputRef }: { label: string; value: string; onChange: (v: string) => void; onPick?: (s: NetworkStop) => void; inputRef?: React.RefObject<TextInput | null> }) {
  const [sugg, setSugg] = useState<NetworkStop[]>([]);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState(false);
  useEffect(() => {
    const q = value.trim();
    if (q.length < 2 || picked) {
      setSugg([]);
      return;
    }
    setLoading(true);
    const h = setTimeout(() => {
      NetworkApi.search(q)
        .then(r => {
          const seen = new Set<string>();
          setSugg(r.stops.filter(s => (seen.has(s.name) ? false : (seen.add(s.name), true))).slice(0, 5));
        })
        .catch(() => setSugg([]))
        .finally(() => setLoading(false));
    }, 280);
    return () => clearTimeout(h);
  }, [value, picked]);
  return (
    <View style={{ zIndex: sugg.length ? 30 : 1 }}>
      <OutlinedInput label={label} value={value} inputRef={inputRef} autoCapitalize="words" onBlur={() => { setPicked(true); setSugg([]); }}
        onChangeText={v => { setPicked(false); onChange(v); }} right={loading ? <ActivityIndicator size="small" color="#999" style={{ marginRight: 10 }} /> : null} />
      {sugg.length ? (
        <View style={styles.sugg}>
          {sugg.map((s, i) => (
            <FadeIn key={s.id} delay={stagger(i, 25)} duration={200}>
              <PressScale hoverLift={false} style={styles.suggRow} onPress={() => { setPicked(true); setSugg([]); onChange(s.name); onPick?.(s); }} accessibilityRole="button">
                <Text style={{ fontSize: 14 }}>🚏</Text>
                <Text style={styles.suggText} numberOfLines={1}>{s.name}</Text>
              </PressScale>
            </FadeIn>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Origin / destination pair with the dotted connector and a round swap button that spins when pressed. */
export function OriginDestination({ from, to, setFrom, setTo, fromLabel, toLabel, swapLabel, fromRef, onPickFrom, onPickTo }: {
  from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void; fromLabel: string; toLabel: string; swapLabel: string;
  fromRef?: React.RefObject<TextInput | null>; onPickFrom?: (s: NetworkStop) => void; onPickTo?: (s: NetworkStop) => void;
}) {
  const spin = useRef(new Animated.Value(0)).current;
  const swap = () => {
    Animated.timing(spin, { toValue: 1, duration: 380, easing: Easing.out(Easing.back(1.5)), useNativeDriver: native }).start(() => spin.setValue(0));
    setFrom(to);
    setTo(from);
  };
  return (
    <View style={[styles.od, { zIndex: 40 }]}>
      <View style={styles.odRail} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <View style={styles.odDot}><Ionicons name="navigate" size={12} color="#FFFFFF" /></View>
        <View style={styles.odLine} />
        <View style={styles.odDot}><Ionicons name="flag" size={12} color="#FFFFFF" /></View>
      </View>
      <View style={{ flex: 1, gap: 14 }}>
        <StopField label={fromLabel} value={from} onChange={setFrom} onPick={onPickFrom} inputRef={fromRef} />
        <StopField label={toLabel} value={to} onChange={setTo} onPick={onPickTo} />
      </View>
      <PressScale hoverLift={false} onPress={swap} style={styles.swap} accessibilityRole="button" accessibilityLabel={swapLabel}>
        <Animated.View style={{ transform: [{ rotate: spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '180deg'] }) }] }}>
          <Ionicons name="swap-vertical" size={22} color="#FFFFFF" />
        </Animated.View>
      </PressScale>
    </View>
  );
}

/** "Recent Search" list. */
export function RecentList({ title, items, onPick, icon = 'time-outline', onClear, clearLabel }: {
  title: string; items: { key: string; label: string }[]; onPick: (key: string) => void; icon?: keyof typeof Ionicons.glyphMap; onClear?: () => void; clearLabel?: string;
}) {
  if (!items.length) return null;
  return (
    <View style={{ marginTop: 22 }}>
      <View style={styles.recentHead}>
        <Text style={styles.recentTitle} accessibilityRole="header">{title}</Text>
        {onClear ? <Text onPress={onClear} style={styles.clear} accessibilityRole="button">{clearLabel}</Text> : null}
      </View>
      <View style={styles.recentBox}>
        {items.map((it, i) => (
          <FadeIn key={it.key} delay={stagger(i, 40)}>
            <PressScale hoverLift={false} style={[styles.recentRow, i > 0 && styles.recentDivider]} onPress={() => onPick(it.key)} accessibilityRole="button" accessibilityLabel={it.label}>
              <Ionicons name={icon} size={24} color="#555" />
              <Text style={styles.recentText} numberOfLines={1}>{it.label}</Text>
              <Ionicons name="chevron-forward" size={16} color="#AAA" />
            </PressScale>
          </FadeIn>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outline: { flexDirection: 'row', alignItems: 'center', minHeight: 56, borderWidth: 1, borderColor: '#B9BCC3', borderRadius: 4, backgroundColor: '#FFFFFF' },
  outlineFocused: { borderColor: '#B1285F', borderWidth: 2 },
  floating: { position: 'absolute', top: -9, left: 10, paddingHorizontal: 4, backgroundColor: '#FFFFFF', fontSize: 12, color: '#55565C' },
  input: { flex: 1, minHeight: 54, paddingHorizontal: 14, fontSize: 16, color: '#1E1E24' },
  sugg: { position: 'absolute', top: 58, left: 0, right: 0, zIndex: 50, backgroundColor: '#FFFFFF', borderRadius: 10, borderWidth: 1, borderColor: '#E3E5EA',
    shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6, paddingVertical: 4 },
  suggRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44, paddingHorizontal: 12 },
  suggText: { flex: 1, fontSize: 14, color: '#1E1E24' },
  od: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  odRail: { alignItems: 'center', alignSelf: 'stretch', justifyContent: 'space-between', paddingVertical: 18 },
  odDot: { width: 24, height: 24, borderRadius: 12, backgroundColor: TEAL, alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: '#C9F3E5' },
  odLine: { flex: 1, width: 0, borderLeftWidth: 2, borderStyle: 'dashed', borderColor: TEAL, marginVertical: 4 },
  swap: { width: 46, height: 46, borderRadius: 23, backgroundColor: TEAL, alignItems: 'center', justifyContent: 'center',
    shadowColor: TEAL, shadowOpacity: 0.4, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
  recentHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  recentTitle: { fontSize: 18, fontWeight: '800', color: '#1E1E24', textDecorationLine: 'underline' },
  clear: { color: '#B1285F', fontWeight: '700', fontSize: 13, padding: 6 },
  recentBox: { borderWidth: 1, borderColor: '#E3E5EA', borderRadius: 4 },
  recentRow: { flexDirection: 'row', alignItems: 'center', gap: 14, minHeight: 64, paddingHorizontal: 18 },
  recentDivider: { borderTopWidth: 1, borderTopColor: '#E3E5EA' },
  recentText: { flex: 1, fontSize: 17, color: '#1E1E24', fontWeight: '600' },
});
