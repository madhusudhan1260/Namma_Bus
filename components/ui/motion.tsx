/**
 * Shared motion kit for ನಮ್ಮ Bus. Transform/opacity only (GPU-friendly), React Native Animated (no extra
 * dependencies), and every primitive respects the OS / browser "reduce motion" setting.
 *
 *   <FadeIn delay={stagger(i)}>…</FadeIn>       entrance: fade + slide (up by default)
 *   <PressScale onPress={…}>…</PressScale>      press: scale 0.97, web hover: lift 2 px
 *   <Skeleton width={120} height={14} />        loading shimmer
 *   <SlideUp visible>…</SlideUp>                bottom-sheet style reveal
 *   <Pulse>…</Pulse>                            gentle "live" pulse (e.g. a live dot)
 */
import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, PressableProps, StyleProp, View, ViewStyle } from 'react-native';
import { useReducedMotion } from '../access/useReducedMotion';

const nativeDriver = Platform.OS !== 'web';
export const EASE_OUT = Easing.bezier(0.22, 1, 0.36, 1);

/** Delay for the i-th item of a list (capped so long lists don't wait forever). */
export const stagger = (i: number, step = 45, max = 8) => Math.min(i, max) * step;

export function FadeIn({
  children,
  delay = 0,
  duration = 420,
  from = 'bottom',
  distance = 14,
  style,
}: {
  children: React.ReactNode;
  delay?: number;
  duration?: number;
  from?: 'bottom' | 'right' | 'left' | 'top' | 'none';
  distance?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) {
      v.setValue(1);
      return;
    }
    const anim = Animated.timing(v, { toValue: 1, duration, delay, easing: EASE_OUT, useNativeDriver: nativeDriver });
    anim.start();
    return () => anim.stop();
  }, [v, delay, duration, reduced]);
  const offset = v.interpolate({ inputRange: [0, 1], outputRange: [distance, 0] });
  const transform =
    from === 'bottom' ? [{ translateY: offset }]
      : from === 'top' ? [{ translateY: Animated.multiply(offset, -1) }]
        : from === 'right' ? [{ translateX: offset }]
          : from === 'left' ? [{ translateX: Animated.multiply(offset, -1) }]
            : [];
  return <Animated.View style={[style, { opacity: v, transform: transform as any }]}>{children}</Animated.View>;
}

type PressScaleProps = Omit<PressableProps, 'style'> & { style?: StyleProp<ViewStyle>; hoverLift?: boolean; children: React.ReactNode };

/** Pressable with a soft scale-down on press and (web) a small lift on hover. */
export function PressScale({ style, hoverLift = true, children, onPressIn, onPressOut, ...rest }: PressScaleProps) {
  const reduced = useReducedMotion();
  const scale = useRef(new Animated.Value(1)).current;
  const [hovered, setHovered] = useState(false);
  const to = (value: number) =>
    reduced ? scale.setValue(1) : Animated.spring(scale, { toValue: value, speed: 40, bounciness: 4, useNativeDriver: nativeDriver }).start();
  return (
    <Pressable
      {...rest}
      onPressIn={e => {
        to(0.97);
        onPressIn?.(e);
      }}
      onPressOut={e => {
        to(1);
        onPressOut?.(e);
      }}
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
    >
      <Animated.View
        style={[
          style,
          { transform: [{ scale }, { translateY: hovered && hoverLift && !reduced ? -2 : 0 }] },
          hovered && hoverLift ? { shadowColor: '#0B2545', shadowOpacity: 0.12, shadowRadius: 12, shadowOffset: { width: 0, height: 6 } } : null,
          Platform.OS === 'web' ? ({ transitionProperty: 'box-shadow', transitionDuration: '160ms' } as any) : null,
        ]}
      >
        {children}
      </Animated.View>
    </Pressable>
  );
}

/** Loading placeholder with a soft shimmer. */
export function Skeleton({ width = '100%', height = 14, radius = 8, style }: { width?: number | `${number}%`; height?: number; radius?: number; style?: StyleProp<ViewStyle> }) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(v, { toValue: 1, duration: 700, easing: Easing.inOut(Easing.quad), useNativeDriver: nativeDriver }),
        Animated.timing(v, { toValue: 0, duration: 700, easing: Easing.inOut(Easing.quad), useNativeDriver: nativeDriver }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [v, reduced]);
  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no"
      style={[{ width, height, borderRadius: radius, backgroundColor: '#E3E9F0', opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.55, 1] }) }, style]}
    />
  );
}

/** Slides content up from the bottom when `visible` (e.g. a sheet of nearby stops). */
export function SlideUp({ visible, children, style, distance = 40 }: { visible: boolean; children: React.ReactNode; style?: StyleProp<ViewStyle>; distance?: number }) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(visible ? 1 : 0)).current;
  useEffect(() => {
    Animated.timing(v, { toValue: visible ? 1 : 0, duration: reduced ? 0 : 360, easing: EASE_OUT, useNativeDriver: nativeDriver }).start();
  }, [v, visible, reduced]);
  return (
    <Animated.View
      pointerEvents={visible ? 'auto' : 'none'}
      style={[style, { opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [distance, 0] }) }] }]}
    >
      {children}
    </Animated.View>
  );
}

/** A gentle repeating pulse (e.g. the "live" dot). */
export function Pulse({ children, style }: { children?: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1400, easing: Easing.out(Easing.quad), useNativeDriver: nativeDriver }));
    loop.start();
    return () => loop.stop();
  }, [v, reduced]);
  return (
    <View style={[{ alignItems: 'center', justifyContent: 'center' }, style]}>
      <Animated.View
        pointerEvents="none"
        style={{
          position: 'absolute', width: '100%', height: '100%', borderRadius: 999, backgroundColor: 'rgba(22,138,69,0.35)',
          opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.8, 0] }),
          transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1, 2.4] }) }],
        }}
      />
      {children}
    </View>
  );
}

/** "Typing…" indicator: three dots rising in turn. */
export function TypingDots({ color = '#12355B' }: { color?: string }) {
  const reduced = useReducedMotion();
  const dots = [useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current];
  useEffect(() => {
    if (reduced) return;
    const loops = dots.map((d, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 140),
          Animated.timing(d, { toValue: 1, duration: 260, easing: Easing.out(Easing.quad), useNativeDriver: nativeDriver }),
          Animated.timing(d, { toValue: 0, duration: 260, easing: Easing.in(Easing.quad), useNativeDriver: nativeDriver }),
          Animated.delay((2 - i) * 140 + 120),
        ])
      )
    );
    loops.forEach(l => l.start());
    return () => loops.forEach(l => l.stop());
  }, [reduced]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', height: 18 }} accessibilityLabel="…" accessibilityRole="progressbar">
      {dots.map((d, i) => (
        <Animated.View
          key={i}
          style={{
            width: 7, height: 7, borderRadius: 4, backgroundColor: color, marginHorizontal: 2.5,
            opacity: d.interpolate({ inputRange: [0, 1], outputRange: [0.35, 1] }),
            transform: [{ translateY: d.interpolate({ inputRange: [0, 1], outputRange: [0, -5] }) }],
          }}
        />
      ))}
    </View>
  );
}
