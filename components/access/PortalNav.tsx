import React from 'react';
import { Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../../constants/theme';

export interface NavItem<K extends string> {
  key: K;
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  /** Optional count badge (e.g. pending items) */
  badge?: number;
}

/** Desktop sidebar for the staff portals (conductor, college, admin). */
export function SideNav<K extends string>({ items, active, onSelect, title }: { items: NavItem<K>[]; active: K; onSelect: (k: K) => void; title?: string }) {
  return (
    <ScrollView contentContainerStyle={{ paddingHorizontal: 12, gap: 2 }}>
      <Text style={styles.brand}>ನಮ್ಮ BUS</Text>
      {title ? <Text style={styles.sideTitle}>{title}</Text> : null}
      {items.map(it => {
        const on = it.key === active;
        return (
          <TouchableOpacity key={it.key} onPress={() => onSelect(it.key)} style={[styles.sideItem, on && styles.sideItemOn]}
            accessibilityRole="tab" accessibilityState={{ selected: on }} accessibilityLabel={it.label}>
            <Ionicons name={it.icon} size={19} color={on ? COLORS.textInverse : COLORS.deepNavy} />
            <Text style={[styles.sideText, on && styles.sideTextOn]} numberOfLines={1}>{it.label}</Text>
            {it.badge ? <Text style={[styles.count, on && styles.countOn]}>{it.badge}</Text> : null}
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

/** Phone bottom navigation: icons + labels, ≥ 56 px tall targets; scrolls sideways when there are many items. */
export function BottomNav<K extends string>({ items, active, onSelect }: { items: NavItem<K>[]; active: K; onSelect: (k: K) => void }) {
  const scroll = items.length > 5;
  const content = items.map(it => {
    const on = it.key === active;
    return (
      <TouchableOpacity key={it.key} onPress={() => onSelect(it.key)} style={[styles.tab, scroll ? styles.tabScroll : styles.tabFlex]}
        accessibilityRole="tab" accessibilityState={{ selected: on }} accessibilityLabel={it.label}>
        <View>
          <Ionicons name={on ? (it.icon.replace('-outline', '') as any) : it.icon} size={22} color={on ? '#C2185B' : COLORS.textSecondary} />
          {it.badge ? <View style={styles.dot}><Text style={styles.dotText}>{it.badge > 9 ? '9+' : it.badge}</Text></View> : null}
        </View>
        <Text style={[styles.tabText, on && styles.tabTextOn]} numberOfLines={1}>{it.label}</Text>
      </TouchableOpacity>
    );
  });
  return (
    <View accessibilityRole="tablist" style={styles.bar}>
      {scroll ? <ScrollView horizontal showsHorizontalScrollIndicator={false}>{content}</ScrollView> : <View style={{ flexDirection: 'row' }}>{content}</View>}
    </View>
  );
}

const styles = StyleSheet.create({
  brand: { fontSize: 20, fontWeight: '900', color: '#C2185B', paddingHorizontal: 10, paddingVertical: 8 },
  sideTitle: { fontSize: 12, fontWeight: '800', color: COLORS.textMuted, paddingHorizontal: 10, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.6 },
  sideItem: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44, paddingHorizontal: 12, borderRadius: 12,
    ...(Platform.OS === 'web' ? ({ cursor: 'pointer' } as any) : null) },
  sideItemOn: { backgroundColor: COLORS.deepNavy },
  sideText: { flex: 1, fontSize: 15, fontWeight: '700', color: COLORS.deepNavy },
  sideTextOn: { color: COLORS.textInverse },
  count: { minWidth: 22, textAlign: 'center', fontSize: 12, fontWeight: '900', color: '#FFFFFF', backgroundColor: '#E0262E', borderRadius: 11, paddingHorizontal: 6, paddingVertical: 2, overflow: 'hidden' },
  countOn: { backgroundColor: '#FFFFFF', color: COLORS.deepNavy },
  bar: { paddingBottom: Platform.OS === 'ios' ? 6 : 2 },
  tab: { alignItems: 'center', justifyContent: 'center', minHeight: 58, paddingVertical: 6, gap: 2 },
  tabFlex: { flex: 1 },
  tabScroll: { minWidth: 76, paddingHorizontal: 8 },
  tabText: { fontSize: 11, fontWeight: '700', color: COLORS.textSecondary },
  tabTextOn: { color: '#C2185B', fontWeight: '900' },
  dot: { position: 'absolute', top: -4, right: -10, minWidth: 16, height: 16, borderRadius: 8, backgroundColor: '#E0262E', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  dotText: { color: '#FFFFFF', fontSize: 9, fontWeight: '900' },
});
