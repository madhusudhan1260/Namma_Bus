import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, StyleSheet, View } from 'react-native';
import { ENTRY_EASING, registerArrivalReveal } from './transition';

const native = Platform.OS !== 'web';

/**
 * Wraps the app's navigator. When a sign-in transition reaches its midpoint the newly shown (existing) dashboard
 * slides in from the right: opacity 0 → 1, translateX 40 → 0, scale 0.98 → 1. Outside a transition it applies no
 * transform at all, so layout, fixed elements and scrolling behave exactly as before.
 */
export function ArrivalReveal({ children }: { children: React.ReactNode }) {
  const progress = useRef(new Animated.Value(1)).current;
  const [animating, setAnimating] = useState(false);

  useEffect(() => {
    registerArrivalReveal(reduced => {
      progress.setValue(0);
      setAnimating(true);
      Animated.timing(progress, {
        toValue: 1,
        duration: reduced ? 220 : 900,
        easing: Easing.bezier(...ENTRY_EASING),
        useNativeDriver: native,
      }).start(() => setAnimating(false));
    });
    return () => registerArrivalReveal(null);
  }, [progress]);

  const style = animating
    ? {
        opacity: progress,
        transform: [
          { translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [40, 0] }) },
          { scale: progress.interpolate({ inputRange: [0, 1], outputRange: [0.98, 1] }) },
        ],
      }
    : null;
  // The outer view clips the 40 px slide so the page never scrolls sideways during the reveal
  return (
    <View style={[styles.fill, animating && styles.clip]}>
      <Animated.View style={[styles.fill, style]}>{children}</Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 }, clip: { overflow: 'hidden' } });
