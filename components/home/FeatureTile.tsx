import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS } from '../../constants/theme';
import { useReducedMotion } from '../access/useReducedMotion';

const native = Platform.OS !== 'web';

/**
 * A home-screen feature tile: white card, coloured round icon, label. Rises in on mount (staggered by `index`),
 * lifts with a coloured glow on hover, the icon wiggles and pops on hover, and the tile scales down when pressed.
 */
export function FeatureTile({ index, icon, color, label, hint, onPress, width, compact = false }: {
  index: number;
  /** Exact tile width from the grid (keeps every tile the same size) */
  width: number;
  /** Smaller tile for phones */
  compact?: boolean;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  label: string;
  hint?: string;
  onPress: () => void;
}) {
  const reduced = useReducedMotion();
  const enter = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const press = useRef(new Animated.Value(1)).current;
  const hover = useRef(new Animated.Value(0)).current;
  const wiggle = useRef(new Animated.Value(0)).current;
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    Animated.timing(enter, {
      toValue: 1, duration: reduced ? 0 : 560, delay: reduced ? 0 : 250 + index * 70,
      easing: Easing.bezier(0.22, 1, 0.36, 1), useNativeDriver: native,
    }).start();
  }, [enter, index, reduced]);

  const onHover = (on: boolean) => {
    setHovered(on);
    if (reduced) return;
    Animated.spring(hover, { toValue: on ? 1 : 0, speed: 16, bounciness: 8, useNativeDriver: native }).start();
    if (on) {
      wiggle.setValue(0);
      Animated.timing(wiggle, { toValue: 1, duration: 520, easing: Easing.linear, useNativeDriver: native }).start();
    }
  };
  const onPressIn = () => !reduced && Animated.spring(press, { toValue: 0.96, speed: 40, bounciness: 4, useNativeDriver: native }).start();
  const onPressOut = () => Animated.spring(press, { toValue: 1, speed: 30, bounciness: 8, useNativeDriver: native }).start();

  const rotate = wiggle.interpolate({ inputRange: [0, 0.2, 0.4, 0.6, 0.8, 1], outputRange: ['0deg', '-12deg', '10deg', '-6deg', '3deg', '0deg'] });

  return (
    <Animated.View
      style={[{ width }, {
        opacity: enter,
        transform: [
          { translateY: Animated.add(enter.interpolate({ inputRange: [0, 1], outputRange: [36, 0] }), hover.interpolate({ inputRange: [0, 1], outputRange: [0, -6] })) },
          { scale: Animated.multiply(press, enter.interpolate({ inputRange: [0, 1], outputRange: [0.94, 1] })) },
        ],
      }]}
    >
      <Pressable
        onPress={onPress}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        onHoverIn={() => onHover(true)}
        onHoverOut={() => onHover(false)}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityHint={hint}
        style={(state: any) => [styles.card, compact && styles.cardCompact, hovered && { shadowColor: color, shadowOpacity: 0.35, shadowRadius: 18 }, state.focused && styles.focus]}
      >
        <Animated.View style={[styles.iconRing, compact && styles.iconRingCompact, { backgroundColor: `${color}22`, transform: [{ scale: hover.interpolate({ inputRange: [0, 1], outputRange: [1, 1.12] }) }] }]}>
          <Animated.View style={[styles.icon, compact && styles.iconCompact, { backgroundColor: color, transform: [{ rotate }, { scale: hover.interpolate({ inputRange: [0, 1], outputRange: [1, 1.08] }) }] }]}>
            <Ionicons name={icon} size={compact ? 24 : 30} color="#FFFFFF" />
          </Animated.View>
        </Animated.View>
        {/* label area always reserves two lines, so every tile has the same height */}
        <View style={[styles.labelBox, compact && styles.labelBoxCompact]}>
          <Text style={[styles.label, compact && styles.labelCompact]} numberOfLines={2}>{label}</Text>
        </View>
        {hint ? <Text style={styles.hint} numberOfLines={2}>{hint}</Text> : null}
        <View style={[styles.underline, { backgroundColor: color, opacity: hovered ? 1 : 0 }]} />
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#FFFFFF', borderRadius: 18, paddingVertical: 20, paddingHorizontal: 10, alignItems: 'center', height: 178, justifyContent: 'center',
    shadowColor: '#3B0A24', shadowOpacity: 0.12, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 4,
    ...(Platform.OS === 'web' ? ({ transitionProperty: 'box-shadow', transitionDuration: '200ms', cursor: 'pointer' } as any) : null),
  },
  focus: { borderWidth: 2, borderColor: COLORS.primary },
  iconRing: { width: 84, height: 84, borderRadius: 42, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  icon: { width: 64, height: 64, borderRadius: 32, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.18, shadowRadius: 6, shadowOffset: { width: 0, height: 3 } },
  cardCompact: { height: 142, paddingVertical: 14, borderRadius: 16 },
  iconRingCompact: { width: 66, height: 66, borderRadius: 33, marginBottom: 8 },
  iconCompact: { width: 50, height: 50, borderRadius: 25 },
  labelBox: { height: 42, justifyContent: 'center' },
  labelBoxCompact: { height: 36 },
  label: { fontSize: 16, fontWeight: '800', color: '#1E1E24', textAlign: 'center', lineHeight: 20 },
  labelCompact: { fontSize: 14, lineHeight: 17 },
  hint: { fontSize: 12, color: COLORS.textSecondary, textAlign: 'center', marginTop: 4 },
  underline: { position: 'absolute', bottom: 0, left: 28, right: 28, height: 3, borderTopLeftRadius: 3, borderTopRightRadius: 3 },
});
