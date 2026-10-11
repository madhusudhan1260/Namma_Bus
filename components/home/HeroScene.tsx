import React, { useEffect, useMemo, useRef } from 'react';
import { Animated, Easing, Platform, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { BUS_BASE_WIDTH, BUS_WHEEL_RADIUS, BusIllustration } from '../access/BusIllustration';
import { useReducedMotion } from '../access/useReducedMotion';

const native = Platform.OS !== 'web';

// Sky: warm pink at the top to deep magenta at the horizon (drawn as soft bands — no gradient library needed)
const SKY = ['#E4566E', '#DD5070', '#D64A72', '#CF4473', '#C83F74', '#C03A74', '#B83574', '#AF3173', '#A52D71', '#9B2A6F', '#91276C', '#872569'];

function useLoop(duration: number, delay = 0, enabled = true) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!enabled) return;
    const loop = Animated.loop(Animated.sequence([
      Animated.delay(delay),
      Animated.timing(v, { toValue: 1, duration, easing: Easing.linear, useNativeDriver: native }),
      Animated.timing(v, { toValue: 0, duration: 0, useNativeDriver: native }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [v, duration, delay, enabled]);
  return v;
}

function useSway(duration: number, enabled = true) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!enabled) return;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(v, { toValue: 1, duration, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
      Animated.timing(v, { toValue: 0, duration, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [v, duration, enabled]);
  return v;
}

function Cloud({ width, top, duration, delay, sceneWidth, reduced, opacity = 0.9 }: { width: number; top: number; duration: number; delay: number; sceneWidth: number; reduced: boolean; opacity?: number }) {
  const t = useLoop(duration, delay, !reduced);
  const h = width * 0.42;
  const x = reduced ? (sceneWidth * delay) / (duration + delay) : t.interpolate({ inputRange: [0, 1], outputRange: [sceneWidth + 20, -width - 20] });
  return (
    <Animated.View style={{ position: 'absolute', top, left: 0, width, height: h, opacity, transform: [{ translateX: x as any }] }}>
      <View style={[styles.puff, { left: width * 0.08, top: h * 0.38, width: width * 0.36, height: width * 0.36 * 0.75, borderRadius: width }]} />
      <View style={[styles.puff, { left: width * 0.28, top: 0, width: width * 0.42, height: width * 0.42, borderRadius: width }]} />
      <View style={[styles.puff, { left: width * 0.56, top: h * 0.26, width: width * 0.32, height: width * 0.32 * 0.85, borderRadius: width }]} />
      <View style={[styles.puff, { left: 0, right: 0, bottom: 0, height: h * 0.4, borderRadius: h }]} />
    </Animated.View>
  );
}

/** Rectangular skyline buildings with windows that switch on and off. */
function Building({ left, width, height, base, color, reduced, seed }: { left: number; width: number; height: number; base: number; color: string; reduced: boolean; seed: number }) {
  const blink = useSway(1800 + (seed % 5) * 400, !reduced);
  const cols = Math.max(2, Math.floor(width / 16));
  const rows = Math.max(2, Math.floor(height / 22));
  const lit = (r: number, c: number) => (r * 7 + c * 13 + seed) % 5 === 0;
  return (
    <View style={{ position: 'absolute', left, bottom: base, width, height, backgroundColor: color }}>
      {Array.from({ length: rows }).map((_, r) => (
        <View key={r} style={{ flexDirection: 'row', justifyContent: 'space-evenly', marginTop: 9 }}>
          {Array.from({ length: cols }).map((__, c) =>
            lit(r, c) ? (
              <Animated.View key={c} style={[styles.window, { opacity: (r + c + seed) % 3 === 0 ? blink : 0.85 }]} />
            ) : (
              <View key={c} style={[styles.window, { opacity: 0.18 }]} />
            )
          )}
        </View>
      ))}
    </View>
  );
}

/** Simplified silhouette of Bengaluru's Vidhana Soudha: wide base, colonnade, central drum and dome. */
function VidhanaSoudha({ width, base, color }: { width: number; base: number; color: string }) {
  const w = width;
  return (
    <View style={{ position: 'absolute', left: '50%', bottom: base, width: w, height: w * 0.42, marginLeft: -w / 2 }} pointerEvents="none">
      <View style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: w * 0.12, backgroundColor: color }} />
      <View style={{ position: 'absolute', bottom: w * 0.12, left: w * 0.08, right: w * 0.08, height: w * 0.1, backgroundColor: color, flexDirection: 'row', justifyContent: 'space-evenly', alignItems: 'flex-end' }}>
        {Array.from({ length: 11 }).map((_, i) => <View key={i} style={{ width: w * 0.012, height: w * 0.08, backgroundColor: 'rgba(255,255,255,0.18)' }} />)}
      </View>
      <View style={{ position: 'absolute', bottom: w * 0.22, left: w * 0.36, right: w * 0.36, height: w * 0.07, backgroundColor: color }} />
      <View style={{ position: 'absolute', bottom: w * 0.29, left: w * 0.41, width: w * 0.18, height: w * 0.09, borderTopLeftRadius: w, borderTopRightRadius: w, backgroundColor: color }} />
      <View style={{ position: 'absolute', bottom: w * 0.38, left: w * 0.494, width: w * 0.012, height: w * 0.04, backgroundColor: color }} />
      {[0.14, 0.78].map(x => (
        <View key={x} style={{ position: 'absolute', bottom: w * 0.22, left: w * x, width: w * 0.08, height: w * 0.05, borderTopLeftRadius: w, borderTopRightRadius: w, backgroundColor: color }} />
      ))}
    </View>
  );
}

function Tree({ left, base, size, reduced, delay = 0 }: { left: number; base: number; size: number; reduced: boolean; delay?: number }) {
  const sway = useSway(2600 + delay, !reduced);
  const rotate = sway.interpolate({ inputRange: [0, 1], outputRange: ['-2deg', '2deg'] });
  return (
    <View style={{ position: 'absolute', left, bottom: base, width: size, height: size * 1.4 }} pointerEvents="none">
      <View style={{ position: 'absolute', bottom: 0, left: size * 0.45, width: size * 0.1, height: size * 0.6, backgroundColor: '#6B4A2B', borderRadius: 3 }} />
      <Animated.View style={{ position: 'absolute', bottom: size * 0.45, left: 0, width: size, height: size, transform: [{ rotate }] }}>
        <View style={{ position: 'absolute', left: 0, top: size * 0.25, width: size * 0.62, height: size * 0.62, borderRadius: size, backgroundColor: '#4E9A3E' }} />
        <View style={{ position: 'absolute', right: 0, top: size * 0.2, width: size * 0.6, height: size * 0.6, borderRadius: size, backgroundColor: '#5BAA48' }} />
        <View style={{ position: 'absolute', left: size * 0.18, top: 0, width: size * 0.64, height: size * 0.64, borderRadius: size, backgroundColor: '#67B652' }} />
      </Animated.View>
    </View>
  );
}

/** A person waiting at the stop (simple silhouette, shifts weight now and then). */
function Person({ left, base, color, h, reduced, delay }: { left: number; base: number; color: string; h: number; reduced: boolean; delay: number }) {
  const sway = useSway(1400 + delay, !reduced);
  return (
    <Animated.View style={{ position: 'absolute', left, bottom: base, alignItems: 'center', transform: [{ translateY: sway.interpolate({ inputRange: [0, 1], outputRange: [0, -1.5] }) }] }}>
      <View style={{ width: h * 0.28, height: h * 0.28, borderRadius: h, backgroundColor: '#5A3A2E' }} />
      <View style={{ width: h * 0.42, height: h * 0.5, borderTopLeftRadius: h * 0.2, borderTopRightRadius: h * 0.2, backgroundColor: color, marginTop: 1 }} />
      <View style={{ flexDirection: 'row', gap: 2 }}>
        <View style={{ width: h * 0.11, height: h * 0.32, backgroundColor: '#2D3142' }} />
        <View style={{ width: h * 0.11, height: h * 0.32, backgroundColor: '#2D3142' }} />
      </View>
    </Animated.View>
  );
}

/** A bus driving right → left along the road, looping; wheels turn in step with the distance it covers. */
function RoadBus({ sceneWidth, bottom, width, duration, delay, reduced }: { sceneWidth: number; bottom: number; width: number; duration: number; delay: number; reduced: boolean }) {
  const t = useLoop(duration, delay, !reduced);
  const startX = sceneWidth + 30;
  const endX = -width - 120;
  const scale = width / BUS_BASE_WIDTH;
  const turns = (startX - endX) / (2 * Math.PI * BUS_WHEEL_RADIUS * scale);
  const translateX = reduced ? sceneWidth * 0.62 : t.interpolate({ inputRange: [0, 1], outputRange: [startX, endX] });
  const wheelRotate = reduced ? '0deg' : t.interpolate({ inputRange: [0, 1], outputRange: ['0deg', `${-turns * 360}deg`] });
  const bob = useSway(160, !reduced);
  return (
    <Animated.View style={{ position: 'absolute', left: 0, bottom, transform: [{ translateX: translateX as any }] }} pointerEvents="none">
      <BusIllustration width={width} headlights lively={!reduced} wheelRotate={wheelRotate as any}
        bodyTransform={reduced ? [] : [{ translateY: bob.interpolate({ inputRange: [0, 1], outputRange: [0, -1] }) }]} />
    </Animated.View>
  );
}

/**
 * Home hero: a Bengaluru street at dusk — pink sky, drifting clouds, skyline with twinkling windows, a Vidhana
 * Soudha silhouette, the ನಮ್ಮ BUS title, trees, people at a bus stop and buses driving by. Decorative only
 * (hidden from screen readers except the title). All motion respects "reduce motion".
 */
export function HeroScene({ height, title, subtitle, topRight, sceneWidth }: {
  height: number;
  title?: React.ReactNode;
  subtitle: string;
  topRight?: React.ReactNode;
  /** Width of the box the scene sits in (defaults to the window width) */
  sceneWidth?: number;
}) {
  const { width: windowWidth } = useWindowDimensions();
  const width = sceneWidth || windowWidth;
  const reduced = useReducedMotion();
  const ground = Math.round(height * 0.2); // road height from the bottom
  const intro = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const float = useSway(3200, !reduced);
  useEffect(() => {
    Animated.timing(intro, { toValue: 1, duration: reduced ? 0 : 900, easing: Easing.bezier(0.22, 1, 0.36, 1), useNativeDriver: native }).start();
  }, [intro, reduced]);

  const buildings = useMemo(() => {
    const out: { left: number; width: number; height: number; seed: number }[] = [];
    let x = -10;
    let i = 0;
    while (x < width) {
      const w = 46 + ((i * 37) % 50);
      const h = height * (0.22 + (((i * 53) % 30) / 100));
      out.push({ left: x, width: w, height: h, seed: i });
      x += w + 6 + ((i * 17) % 14);
      i++;
    }
    return out;
  }, [width, height]);

  const busW = Math.min(250, Math.max(150, width * 0.24));
  const titleSize = Math.min(78, Math.max(46, width * 0.085));

  return (
    <View style={[styles.scene, { height }]}>
      <View style={StyleSheet.absoluteFill} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" aria-hidden>
        {SKY.map((c, i) => (
          <View key={c} style={{ position: 'absolute', left: 0, right: 0, top: (height * i) / SKY.length, height: height / SKY.length + 1, backgroundColor: c }} />
        ))}
        {/* soft glow behind the title */}
        <View style={[styles.glow, { width: width * 0.7, height: width * 0.7, borderRadius: width, left: width * 0.15, top: -width * 0.32 }]} />

        <Cloud width={150} top={height * 0.1} duration={46000} delay={0} sceneWidth={width} reduced={reduced} />
        <Cloud width={110} top={height * 0.28} duration={62000} delay={9000} sceneWidth={width} reduced={reduced} opacity={0.75} />
        <Cloud width={180} top={height * 0.04} duration={78000} delay={22000} sceneWidth={width} reduced={reduced} opacity={0.6} />
        <Cloud width={90} top={height * 0.36} duration={54000} delay={30000} sceneWidth={width} reduced={reduced} opacity={0.8} />

        {buildings.map(b => (
          <Building key={b.seed} left={b.left} width={b.width} height={b.height} base={ground} color="rgba(135, 28, 75, 0.55)" reduced={reduced} seed={b.seed} />
        ))}
        <VidhanaSoudha width={Math.min(520, width * 0.62)} base={ground} color="rgba(110, 18, 52, 0.75)" />

        <Tree left={width * 0.03} base={ground - 4} size={Math.min(90, width * 0.12)} reduced={reduced} />
        <Tree left={width * 0.88} base={ground - 4} size={Math.min(76, width * 0.1)} reduced={reduced} delay={600} />

        {/* pavement, bus stop and people waiting */}
        <View style={[styles.pavement, { bottom: ground - 8, height: 10 }]} />
        <View style={{ position: 'absolute', left: width * 0.16, bottom: ground + 2, alignItems: 'center' }}>
          <View style={styles.stopSign}><Text style={styles.stopSignText}>🚏</Text></View>
          <View style={styles.stopPole} />
        </View>
        <Person left={width * 0.2} base={ground + 2} color="#2F6FD6" h={26} reduced={reduced} delay={0} />
        <Person left={width * 0.225} base={ground + 2} color="#E7884A" h={23} reduced={reduced} delay={300} />
        <Person left={width * 0.25} base={ground + 2} color="#7A4FB5" h={27} reduced={reduced} delay={700} />

        {/* road */}
        <View style={[styles.road, { height: ground - 8 }]}>
          <View style={styles.lanes}>
            {Array.from({ length: Math.ceil(width / 70) + 1 }).map((_, i) => <View key={i} style={styles.dash} />)}
          </View>
        </View>
        <RoadBus sceneWidth={width} bottom={ground * 0.42} width={busW} duration={11000} delay={600} reduced={reduced} />
        <RoadBus sceneWidth={width} bottom={ground * 0.06} width={busW * 0.88} duration={15000} delay={6500} reduced={reduced} />
      </View>

      {/* title */}
      <View style={styles.topRow}>{topRight}</View>
      <Animated.View
        style={[styles.titleWrap, { top: width < 560 ? 62 : '13%' }, {
          opacity: intro,
          transform: [
            { translateY: Animated.add(intro.interpolate({ inputRange: [0, 1], outputRange: [24, 0] }), float.interpolate({ inputRange: [0, 1], outputRange: [0, -4] })) },
            { scale: intro.interpolate({ inputRange: [0, 1], outputRange: [0.92, 1] }) },
          ],
        }]}
      >
        {title ?? (
          <Text style={[styles.title, { fontSize: titleSize, lineHeight: titleSize * 1.15 }]} accessibilityRole="header">
            <Text style={styles.titleKn}>ನಮ್ಮ </Text>BUS
          </Text>
        )}
        <Text style={styles.subtitle}>{subtitle}</Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  scene: { width: '100%', overflow: 'hidden', backgroundColor: '#B83574' },
  glow: { position: 'absolute', backgroundColor: 'rgba(255, 210, 220, 0.18)' },
  puff: { position: 'absolute', backgroundColor: '#FBE3EA' },
  window: { width: 6, height: 8, borderRadius: 1, backgroundColor: '#FFD9E4' },
  pavement: { position: 'absolute', left: 0, right: 0, backgroundColor: '#C9C2B8' },
  road: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: '#2B2F38', justifyContent: 'center' },
  lanes: { flexDirection: 'row' },
  dash: { width: 34, height: 4, borderRadius: 2, marginRight: 36, backgroundColor: '#E8E2D0' },
  stopSign: { width: 22, height: 22, borderRadius: 5, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  stopSignText: { fontSize: 13 },
  stopPole: { width: 3, height: 26, backgroundColor: '#E8E2D0' },
  topRow: { position: 'absolute', top: 12, right: 12, flexDirection: 'row', gap: 8, zIndex: 3 },
  titleWrap: { position: 'absolute', top: '13%', left: 0, right: 0, alignItems: 'center', paddingHorizontal: 16 },
  title: { color: '#7E1426', fontWeight: '900', letterSpacing: 2, textAlign: 'center', textShadowColor: 'rgba(255,255,255,0.35)', textShadowRadius: 8, textShadowOffset: { width: 0, height: 2 } },
  titleKn: { color: '#FFFFFF', fontWeight: '900' },
  subtitle: { color: '#FFF1F5', fontWeight: '800', fontSize: 15, marginTop: 4, textAlign: 'center', letterSpacing: 0.5 },
});
