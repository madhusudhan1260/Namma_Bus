import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import { BUS_BASE_WIDTH, BUS_WHEEL_RADIUS, BusIllustration } from './BusIllustration';
import { ENTRY_EASING, busDurationMs, navigateAtMs, registerTransitionHost } from './transition';

const native = Platform.OS !== 'web';
const ease = Easing.bezier(...ENTRY_EASING);

/**
 * The bus driving RIGHT → LEFT across the screen after a successful sign-in. Transform/opacity only, pointer
 * events disabled, clipped to the viewport (no horizontal scrolling). `onMidpoint` fires when the destination
 * should be shown behind it; `onComplete` when the bus has left the screen.
 *
 * Realism: one position value drives everything. The wheels turn by exactly distance ÷ circumference, the body
 * (on its "suspension") pitches nose-up while accelerating and dips as it eases off, with a small road vibration;
 * the wheels and shadow stay on a fixed road with lane markings.
 */
export function BusTransition({ onMidpoint, onComplete }: { onMidpoint: () => void; onComplete: () => void }) {
  const { width, height } = useWindowDimensions();
  const busWidth = Math.round(Math.min(380, Math.max(220, width * 0.5)));
  const scale = busWidth / BUS_BASE_WIDTH;
  const busHeight = 106 * scale;
  const startX = width + 24;
  const endX = -busWidth - 90; // includes the headlight beam ahead of the bus
  const distance = startX - endX;
  const wheelTurns = distance / (2 * Math.PI * BUS_WHEEL_RADIUS * scale);
  const groundY = Math.round(height * 0.45 - busHeight / 2); // bus sits a little above the middle of the screen

  const pos = useRef(new Animated.Value(startX)).current;
  const vibe = useRef(new Animated.Value(0)).current;
  const fade = useRef(new Animated.Value(0)).current;

  // Navigate exactly once (midpoint timer or a skip tap, whichever comes first)
  const navigated = useRef(false);
  const navigateOnce = () => {
    if (navigated.current) return;
    navigated.current = true;
    onMidpoint();
  };
  const skip = () => {
    navigateOnce();
    pos.stopAnimation();
    onComplete();
  };

  useEffect(() => {
    const BUS_DURATION_MS = busDurationMs();
    const mid = setTimeout(navigateOnce, navigateAtMs());
    // Safety net: if animation frames are paused (background tab), never leave the overlay stuck on screen
    const safety = setTimeout(() => { navigateOnce(); onComplete(); }, BUS_DURATION_MS + 600);
    const vibration = Animated.loop(
      Animated.sequence([
        Animated.timing(vibe, { toValue: -1, duration: 85, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
        Animated.timing(vibe, { toValue: 0.4, duration: 95, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
        Animated.timing(vibe, { toValue: -0.6, duration: 80, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
        Animated.timing(vibe, { toValue: 0, duration: 90, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
      ])
    );
    vibration.start();
    Animated.parallel([
      // pulls in already moving, accelerates, cruises, eases off slightly as it leaves
      Animated.timing(pos, { toValue: endX, duration: BUS_DURATION_MS, easing: Easing.bezier(0.32, 0.06, 0.38, 1), useNativeDriver: native }),
      Animated.sequence([
        Animated.timing(fade, { toValue: 1, duration: BUS_DURATION_MS * 0.3, easing: ease, useNativeDriver: native }),
        Animated.delay(BUS_DURATION_MS * 0.35),
        Animated.timing(fade, { toValue: 0, duration: BUS_DURATION_MS * 0.35, easing: ease, useNativeDriver: native }),
      ]),
    ]).start(() => {
      vibration.stop();
      onComplete();
    });
    return () => {
      clearTimeout(mid);
      clearTimeout(safety);
      vibration.stop();
    };
    // run once per mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const range = [endX, endX + distance * 0.3, startX - distance * 0.28, startX];
  const wheelRotate = pos.interpolate({ inputRange: [endX, startX], outputRange: [`${-wheelTurns * 360}deg`, '0deg'] });
  const pitch = pos.interpolate({ inputRange: range, outputRange: ['-0.45deg', '0deg', '0deg', '0.8deg'] });
  const vibeY = vibe.interpolate({ inputRange: [-1, 1], outputRange: [-1.3 * scale, 1.3 * scale] });
  const streaks = pos.interpolate({ inputRange: range, outputRange: [0.1, 0.6, 0.6, 0.15] });
  // brake light glows while the bus eases off (last stretch, as it leaves on the left)
  const brake = pos.interpolate({ inputRange: [endX, endX + distance * 0.35, endX + distance * 0.5, startX], outputRange: [1, 0.9, 0, 0] });

  return (
    <Pressable onPress={skip} style={styles.overlay} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      aria-hidden testID="bus-transition">
      <Animated.View style={[styles.full, styles.tint, { opacity: fade.interpolate({ inputRange: [0, 1], outputRange: [0, 0.1] }) }]} />
      {/* fixed road: kerb line and lane markings (the camera is still; only the bus moves) */}
      <Animated.View style={[styles.road, { top: groundY + busHeight - 2, opacity: fade }]}>
        <View style={styles.kerb} />
        <View style={styles.lanes}>
          {Array.from({ length: Math.ceil(width / 70) + 1 }).map((_, i) => (
            <View key={i} style={styles.dash} />
          ))}
        </View>
      </Animated.View>
      <Animated.View style={{ position: 'absolute', left: 0, top: groundY, transform: [{ translateX: pos }] }}>
        <Animated.View style={[styles.streaks, { left: busWidth + 6, top: busHeight * 0.25, opacity: streaks }]}>
          {[0, 1, 2].map(i => (
            <View key={i} style={[styles.streak, { width: 30 + i * 14, marginLeft: i * 8 }]} />
          ))}
        </Animated.View>
        <BusIllustration width={busWidth} headlights lively brake={brake} wheelRotate={wheelRotate}
          bodyTransform={[{ translateY: vibeY }, { rotate: pitch }]} />
      </Animated.View>
    </Pressable>
  );
}

/** Mounted once in the root layout; plays the bus whenever a sign-in succeeds. */
export function TransitionHost() {
  const [run, setRun] = useState<{ key: number; navigate: () => void; done: () => void } | null>(null);
  const keyRef = useRef(0);

  useEffect(() => {
    registerTransitionHost(({ reduced, navigate, done }) => {
      if (reduced) {
        // Reduced motion: no bus, just a short fade handled by ArrivalReveal
        navigate();
        setTimeout(done, 200);
        return;
      }
      keyRef.current += 1;
      setRun({ key: keyRef.current, navigate, done });
    });
    return () => registerTransitionHost(null);
  }, []);

  const complete = useCallback(() => {
    if (!run) return; // safety timer and animation end may both fire
    run.done();
    setRun(null);
  }, [run]);

  if (!run) return null;
  return <BusTransition key={run.key} onMidpoint={run.navigate} onComplete={complete} />;
}

const styles = StyleSheet.create({
  overlay: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, overflow: 'hidden', zIndex: 1000, elevation: 1000 },
  full: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  tint: { backgroundColor: '#12355B' },
  road: { position: 'absolute', left: 0, right: 0 },
  kerb: { height: 3, backgroundColor: 'rgba(18, 53, 91, 0.28)' },
  lanes: { flexDirection: 'row', marginTop: 14 },
  dash: { width: 38, height: 3, borderRadius: 2, marginRight: 32, backgroundColor: 'rgba(18, 53, 91, 0.22)' },
  streaks: { position: 'absolute' },
  streak: { height: 2, borderRadius: 1, backgroundColor: 'rgba(18, 53, 91, 0.35)', marginBottom: 10 },
});
