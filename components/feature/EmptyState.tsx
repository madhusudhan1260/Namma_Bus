import React, { useEffect, useRef } from 'react';
import { Animated, Easing, Platform, StyleSheet, Text, View } from 'react-native';
import { BusIllustration } from '../access/BusIllustration';
import { useReducedMotion } from '../access/useReducedMotion';

const native = Platform.OS !== 'web';

/**
 * Friendly empty / "nothing found" state: a bus-stop shelter in a pale city, a bus that drives in and stops,
 * a blinking traffic light and drifting clouds.
 */
export function EmptyState({ title, message, compact = false }: { title: string; message: string; compact?: boolean }) {
  const reduced = useReducedMotion();
  const busIn = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const cloud = useRef(new Animated.Value(0)).current;
  const light = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) return;
    Animated.timing(busIn, { toValue: 1, duration: 1300, delay: 200, easing: Easing.bezier(0.2, 0.8, 0.3, 1), useNativeDriver: native }).start();
    const loops = [
      Animated.loop(Animated.sequence([
        Animated.timing(cloud, { toValue: 1, duration: 6000, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
        Animated.timing(cloud, { toValue: 0, duration: 6000, easing: Easing.inOut(Easing.sin), useNativeDriver: native }),
      ])),
      Animated.loop(Animated.sequence([
        Animated.timing(light, { toValue: 1, duration: 600, useNativeDriver: native }),
        Animated.timing(light, { toValue: 0, duration: 600, useNativeDriver: native }),
      ])),
    ];
    loops.forEach(l => l.start());
    return () => loops.forEach(l => l.stop());
  }, [busIn, cloud, light, reduced]);

  const w = compact ? 260 : 320;
  const h = compact ? 150 : 190;
  return (
    <View style={styles.wrap} accessibilityRole="summary">
      <View style={{ width: w, height: h }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        {/* pale skyline */}
        {[[10, 60, 70], [80, 40, 95], [130, 55, 60], [200, 45, 110], [250, 60, 75]].map(([x, bw, bh], i) => (
          <View key={i} style={{ position: 'absolute', left: (x * w) / 320, bottom: 16, width: (bw * w) / 320, height: (bh * h) / 190, backgroundColor: '#ECEDF1', borderTopLeftRadius: 3, borderTopRightRadius: 3 }} />
        ))}
        <View style={{ position: 'absolute', right: 0, bottom: 16, width: 0, height: 0, borderLeftWidth: w * 0.35, borderBottomWidth: h * 0.55, borderLeftColor: 'transparent', borderBottomColor: '#F1F2F5' }} />
        {/* clouds */}
        <Animated.View style={[styles.cloud, { top: 4, left: w * 0.15, width: w * 0.32, transform: [{ translateX: cloud.interpolate({ inputRange: [0, 1], outputRange: [0, 18] }) }] }]} />
        <Animated.View style={[styles.cloud, { top: 26, left: w * 0.55, width: w * 0.2, transform: [{ translateX: cloud.interpolate({ inputRange: [0, 1], outputRange: [0, -14] }) }] }]} />
        {/* bus stop shelter */}
        <View style={{ position: 'absolute', left: w * 0.05, bottom: 16, width: w * 0.06, height: h * 0.62, backgroundColor: '#D6455F' }} />
        <View style={{ position: 'absolute', left: w * 0.11, bottom: 16, width: w * 0.03, height: h * 0.62, backgroundColor: '#F28C28' }} />
        <View style={{ position: 'absolute', left: w * 0.05, bottom: 16 + h * 0.6, width: w * 0.3, height: h * 0.1, borderTopRightRadius: h * 0.12, backgroundColor: '#D6455F' }} />
        <View style={{ position: 'absolute', left: w * 0.27, bottom: 16 + h * 0.47, width: w * 0.04, height: h * 0.15, borderBottomRightRadius: 8, backgroundColor: '#D6455F' }} />
        {/* traffic light */}
        <View style={{ position: 'absolute', right: w * 0.12, bottom: 16, width: 3, height: h * 0.42, backgroundColor: '#3A3F4B' }} />
        <View style={{ position: 'absolute', right: w * 0.12 - 6, bottom: 16 + h * 0.42, width: 15, height: 30, borderRadius: 6, backgroundColor: '#3A3F4B', alignItems: 'center', justifyContent: 'space-evenly' }}>
          <Animated.View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: '#F5B400', opacity: light }} />
          <Animated.View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: '#3DDC84', opacity: light.interpolate({ inputRange: [0, 1], outputRange: [1, 0.25] }) }} />
        </View>
        {/* road + bus driving in */}
        <View style={{ position: 'absolute', left: 0, right: 0, bottom: 10, height: 6, backgroundColor: '#3A3F4B', borderRadius: 3 }} />
        <Animated.View style={{ position: 'absolute', left: w * 0.36, bottom: 12, opacity: busIn.interpolate({ inputRange: [0, 0.2, 1], outputRange: [0, 1, 1] }),
          transform: [{ translateX: busIn.interpolate({ inputRange: [0, 1], outputRange: [w * 0.7, 0] }) }] }}>
          <BusIllustration width={w * 0.5} wheelRotate={busIn.interpolate({ inputRange: [0, 1], outputRange: ['-540deg', '0deg'] }) as any} lively={!reduced} />
        </Animated.View>
      </View>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.message}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', paddingVertical: 18 },
  cloud: { position: 'absolute', height: 12, borderRadius: 12, backgroundColor: '#E7E8EC' },
  title: { fontSize: 19, fontWeight: '700', color: '#1E1E24', marginTop: 16, textAlign: 'center' },
  message: { fontSize: 14, color: '#55565C', marginTop: 6, textAlign: 'center', lineHeight: 20, maxWidth: 320 },
});
