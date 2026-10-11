import React, { useEffect, useRef } from 'react';
import { Animated, Easing, Platform, StyleSheet, Text, View } from 'react-native';

const nativeDriver = Platform.OS !== 'web';

/**
 * Side view of a Bengaluru low-floor city bus, drawn with plain Views (no image assets). It faces LEFT (front on
 * the left) because it drives right → left in the sign-in transition.
 *
 * Proportions follow a ~12 m × 3 m city bus. The body and the wheels are separate layers so the transition can
 * move them independently: `bodyTransform` (suspension bounce / pitch) applies to the body only, and `wheelRotate`
 * turns the wheels in step with the distance travelled. `headlights` adds a soft beam ahead of the bus.
 */
export const BUS_BASE_WIDTH = 320;
export const BUS_WHEEL_RADIUS = 15; // in base units (scaled by width / BUS_BASE_WIDTH)

type Props = {
  width?: number;
  wheelRotate?: Animated.AnimatedInterpolation<string> | string;
  bodyTransform?: any[];
  headlights?: boolean;
  /** Small "alive" details: alternating LED board, blinking indicator, dust behind the rear wheel, beam shimmer */
  lively?: boolean;
  /** 0 → 1 brake-light glow (e.g. while easing off) */
  brake?: Animated.AnimatedInterpolation<number> | number;
};

// Passenger silhouettes: which windows have someone in them, and where
const PASSENGERS: [number, number][] = [[80, 0.9], [112, 1], [150, 0.85], [214, 1], [250, 0.9], [284, 0.95]];

const WINDOWS = [
  // [left, width] in base units, behind the front door; the middle door sits at 176–202
  [72, 30], [106, 30], [140, 30], [206, 30], [240, 30], [274, 30],
];
const AXLES = [66, 262];

export function BusIllustration({ width = 240, wheelRotate = '0deg', bodyTransform, headlights = false, lively = false, brake = 0 }: Props) {
  const s = width / BUS_BASE_WIDTH;
  const u = (n: number) => n * s;
  const r = u(BUS_WHEEL_RADIUS);

  // ---- small looping details (only when `lively`) ----
  const blink = useRef(new Animated.Value(1)).current;
  const board = useRef(new Animated.Value(0)).current;
  const puff = useRef(new Animated.Value(0)).current;
  const shimmer = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!lively) return;
    const loops = [
      Animated.loop(Animated.sequence([
        Animated.timing(blink, { toValue: 0.15, duration: 1, useNativeDriver: nativeDriver }),
        Animated.delay(330),
        Animated.timing(blink, { toValue: 1, duration: 1, useNativeDriver: nativeDriver }),
        Animated.delay(330),
      ])),
      Animated.loop(Animated.sequence([
        Animated.delay(650),
        Animated.timing(board, { toValue: 1, duration: 260, easing: Easing.inOut(Easing.quad), useNativeDriver: nativeDriver }),
        Animated.delay(650),
        Animated.timing(board, { toValue: 0, duration: 260, easing: Easing.inOut(Easing.quad), useNativeDriver: nativeDriver }),
      ])),
      Animated.loop(Animated.timing(puff, { toValue: 1, duration: 620, easing: Easing.out(Easing.quad), useNativeDriver: nativeDriver })),
      Animated.loop(Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 180, useNativeDriver: nativeDriver }),
        Animated.timing(shimmer, { toValue: 0, duration: 220, useNativeDriver: nativeDriver }),
      ])),
    ];
    loops.forEach(l => l.start());
    return () => loops.forEach(l => l.stop());
  }, [lively, blink, board, puff, shimmer]);

  // three dust puffs behind the rear wheel, staggered along one loop
  const puffs = [0, 0.33, 0.66].map((offset, i) => {
    const t = Animated.modulo(Animated.add(puff, offset), 1);
    return (
      <Animated.View
        key={i}
        style={[styles.puff, {
          left: u(262 + 14), top: u(92), width: u(10), height: u(10), borderRadius: u(5),
          opacity: t.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 0.38, 0] }),
          transform: [
            { translateX: t.interpolate({ inputRange: [0, 1], outputRange: [0, u(34)] }) },
            { translateY: t.interpolate({ inputRange: [0, 1], outputRange: [0, -u(10)] }) },
            { scale: t.interpolate({ inputRange: [0, 1], outputRange: [0.5, 1.9] }) },
          ],
        }]}
      />
    );
  });

  const wheel = (cx: number) => (
    <Animated.View
      key={cx}
      style={[styles.tyre, { left: u(cx) - r, top: u(104) - r * 2, width: r * 2, height: r * 2, borderRadius: r, borderWidth: Math.max(2, u(4)),
        transform: [{ rotate: wheelRotate as any }] }]}
    >
      <View style={[styles.rim, { width: r * 1.15, height: r * 1.15, borderRadius: r }]} />
      {[0, 36, 72, 108, 144].map(a => (
        <View key={a} style={[styles.spoke, { width: r * 1.1, height: Math.max(1.5, u(2.2)), transform: [{ rotate: `${a}deg` }] }]} />
      ))}
      <View style={[styles.hub, { width: r * 0.45, height: r * 0.45, borderRadius: r }]} />
    </Animated.View>
  );

  return (
    <View style={{ width, height: u(106) }} accessible accessibilityRole="image" accessibilityLabel="Namma Bus">
      {/* headlight beam on the road ahead (left) */}
      {headlights ? (
        <>
          {/* soft outer glow, then a brighter core close to the lamp: a tapered warm beam */}
          <View style={[styles.beamOuter, { left: u(-64), top: u(63), width: u(70), height: u(14), borderRadius: u(10) }]} />
          <Animated.View style={[styles.beamCore, { left: u(-30), top: u(66), width: u(36), height: u(8), borderRadius: u(6),
            opacity: lively ? shimmer.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1] }) : 1 }]} />
        </>
      ) : null}
      {/* contact shadow under the bus (stays on the road) */}
      <View style={[styles.shadow, { left: u(18), right: u(10), top: u(99), height: u(7), borderRadius: u(7) }]} />

      {lively ? puffs : null}
      {/* ---------------- body (suspension layer) ---------------- */}
      <Animated.View style={[styles.layer, { transform: bodyTransform || [] }]}>
        {/* roof AC pod */}
        <View style={[styles.acPod, { left: u(118), top: u(3), width: u(118), height: u(10), borderRadius: u(5) }]} />
        {/* shell */}
        <View style={[styles.shell, { left: 0, top: u(10), width: u(320), height: u(76), borderTopLeftRadius: u(22), borderBottomLeftRadius: u(7),
          borderTopRightRadius: u(10), borderBottomRightRadius: u(6) }]}>
          {/* roof highlight */}
          <View style={[styles.roofShine, { height: u(6) }]} />
          {/* livery: red band + orange pinstripe + lower skirt */}
          <View style={[styles.band, { top: u(46), height: u(9) }]} />
          <View style={[styles.pin, { top: u(55), height: u(3) }]} />
          <View style={[styles.skirt, { top: u(58), height: u(18) }]} />
          {/* window band (continuous dark glass behind pillars) */}
          <View style={[styles.glassBand, { left: u(70), top: u(12), width: u(240), height: u(30), borderRadius: u(3) }]} />
          {WINDOWS.map(([x, w]) => (
            <View key={x} style={[styles.window, { left: u(x), top: u(13), width: u(w), height: u(28), borderRadius: u(3) }]}>
              <View style={[styles.glare, { width: u(5), height: u(40), left: u(w * 0.55) }]} />
            </View>
          ))}
          {PASSENGERS.map(([x, k]) => (
            <View key={`p${x}`} style={{ position: 'absolute', left: u(x), top: u(19 + (1 - k) * 8) }}>
              <View style={[styles.head, { width: u(9 * k), height: u(10 * k), borderRadius: u(5) }]} />
              <View style={[styles.shoulders, { width: u(16 * k), height: u(8), borderTopLeftRadius: u(7), borderTopRightRadius: u(7), marginLeft: -u(3.5 * k) }]} />
            </View>
          ))}
          {/* windscreen (raked) with wiper */}
          <View style={[styles.windscreen, { left: u(3), top: u(14), width: u(32), height: u(36), borderTopLeftRadius: u(18), borderRadius: u(4) }]}>
            <View style={[styles.glare, { width: u(6), height: u(50), left: u(14) }]} />
            <View style={[styles.wiper, { left: u(10), bottom: u(4), width: u(16), height: u(1.6) }]} />
          </View>
          {/* LED destination board */}
          <View style={[styles.board, { left: u(10), top: u(3), width: u(86), height: u(9), borderRadius: u(2) }]}>
            <Animated.Text style={[styles.boardText, { fontSize: u(7), opacity: lively ? board.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }) : 1 }]} numberOfLines={1}>
              ನಮ್ಮ BUS
            </Animated.Text>
            {lively ? (
              <Animated.Text style={[styles.boardText, styles.boardAlt, { fontSize: u(6.5), opacity: board }]} numberOfLines={1}>ಸ್ವಾಗತ · WELCOME</Animated.Text>
            ) : null}
          </View>
          {/* "ನಮ್ಮ BUS" side lettering on the lower panel, between the front wheel and the middle door */}
          <View style={[styles.lettering, { left: u(90), top: u(58), width: u(84), height: u(18) }]}>
            <Text style={[styles.namma, { fontSize: u(11.5) }]}>ನಮ್ಮ</Text>
            <Text style={[styles.busWord, { fontSize: u(11), marginLeft: u(3) }]}>BUS</Text>
          </View>
          {/* front door + middle door (two leaves each, low floor) */}
          {[38, 176].map(x => (
            <View key={x} style={[styles.door, { left: u(x), top: u(12), width: u(28), height: u(62), borderRadius: u(2) }]}>
              <View style={[styles.doorLeaf, { marginRight: u(1) }]} />
              <View style={styles.doorLeaf} />
            </View>
          ))}
          {/* wheel arches */}
          {AXLES.map(cx => (
            <View key={cx} style={[styles.arch, { left: u(cx - 19), top: u(58), width: u(38), height: u(22), borderTopLeftRadius: u(19), borderTopRightRadius: u(19) }]} />
          ))}
          {/* lights and bumper */}
          <View style={[styles.headlight, { left: u(2), top: u(58), width: u(10), height: u(6), borderRadius: u(2) }]} />
          <Animated.View style={[styles.indicator, { left: u(2), top: u(65), width: u(6), height: u(3), borderRadius: u(1), opacity: lively ? blink : 1 }]} />
          <View style={[styles.bumper, { left: 0, top: u(70), width: u(34), height: u(6), borderBottomLeftRadius: u(6) }]} />
          <View style={[styles.taillight, { right: u(1), top: u(48), width: u(5), height: u(14), borderRadius: u(2) }]} />
          <Animated.View style={[styles.brakeGlow, { right: u(-3), top: u(45), width: u(11), height: u(20), borderRadius: u(6), opacity: brake as any }]} />
          <View style={[styles.bumper, { right: 0, top: u(70), width: u(14), height: u(6), borderBottomRightRadius: u(5) }]} />
        </View>
        {/* mirror on its arm, ahead of the windscreen */}
        <View style={[styles.mirrorArm, { left: u(-7), top: u(20), width: u(10), height: u(2) }]} />
        <View style={[styles.mirror, { left: u(-10), top: u(18), width: u(5), height: u(12), borderRadius: u(2) }]} />
      </Animated.View>

      {/* ---------------- wheels (stay on the road) ---------------- */}
      {AXLES.map(wheel)}
    </View>
  );
}

const styles = StyleSheet.create({
  layer: { position: 'absolute', left: 0, top: 0, right: 0, bottom: 0 },
  beamOuter: { position: 'absolute', backgroundColor: 'rgba(255, 210, 90, 0.22)' },
  beamCore: { position: 'absolute', backgroundColor: 'rgba(255, 228, 140, 0.5)' },
  shadow: { position: 'absolute', backgroundColor: 'rgba(10, 25, 50, 0.22)' },
  acPod: { position: 'absolute', backgroundColor: '#E3E7ED', borderWidth: 1, borderColor: '#CDD4DD' },
  shell: { position: 'absolute', backgroundColor: '#F7F7F4', borderWidth: 1.5, borderColor: '#C9D0D9', overflow: 'hidden' },
  roofShine: { position: 'absolute', left: 0, right: 0, top: 0, backgroundColor: '#FFFFFF' },
  band: { position: 'absolute', left: 0, right: 0, backgroundColor: '#C62828' },
  pin: { position: 'absolute', left: 0, right: 0, backgroundColor: '#F28C28' },
  skirt: { position: 'absolute', left: 0, right: 0, backgroundColor: '#E6E9EE' },
  glassBand: { position: 'absolute', backgroundColor: '#1A2F4A' },
  window: { position: 'absolute', backgroundColor: '#24476F', overflow: 'hidden' },
  glare: { position: 'absolute', top: -6, backgroundColor: 'rgba(255,255,255,0.13)', transform: [{ rotate: '24deg' }] },
  windscreen: { position: 'absolute', backgroundColor: '#22446A', overflow: 'hidden' },
  wiper: { position: 'absolute', backgroundColor: '#0E1A28', transform: [{ rotate: '-28deg' }] },
  board: { position: 'absolute', backgroundColor: '#111111', justifyContent: 'center', paddingHorizontal: 3 },
  boardText: { color: '#FFB020', fontWeight: '900', letterSpacing: 0.4 },
  door: { position: 'absolute', flexDirection: 'row', padding: 2, backgroundColor: '#9AA6B4' },
  doorLeaf: { flex: 1, backgroundColor: '#2A5280', borderRadius: 1 },
  arch: { position: 'absolute', backgroundColor: '#1B2129' },
  headlight: { position: 'absolute', backgroundColor: '#FFF3B0', borderWidth: 1, borderColor: '#E0C860' },
  indicator: { position: 'absolute', backgroundColor: '#FF9F1C' },
  taillight: { position: 'absolute', backgroundColor: '#D32F2F' },
  bumper: { position: 'absolute', backgroundColor: '#3A424D' },
  brakeGlow: { position: 'absolute', backgroundColor: 'rgba(255, 40, 40, 0.55)' },
  puff: { position: 'absolute', backgroundColor: 'rgba(140, 125, 105, 0.9)' },
  head: { backgroundColor: '#13263C' },
  shoulders: { backgroundColor: '#13263C' },
  boardAlt: { position: 'absolute', left: 3, right: 3 },
  lettering: { position: 'absolute', flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  namma: { color: '#C62828', fontWeight: '900' },
  busWord: { color: '#12355B', fontWeight: '900', letterSpacing: 1 },
  mirrorArm: { position: 'absolute', backgroundColor: '#2B323C' },
  mirror: { position: 'absolute', backgroundColor: '#2B323C' },
  tyre: { position: 'absolute', backgroundColor: '#1E232B', borderColor: '#14181E', alignItems: 'center', justifyContent: 'center' },
  rim: { position: 'absolute', backgroundColor: '#AEB7C2' },
  spoke: { position: 'absolute', backgroundColor: '#6E7884' },
  hub: { position: 'absolute', backgroundColor: '#D5DBE2' },
});
