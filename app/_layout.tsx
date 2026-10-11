import React, { useEffect, useState } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { COLORS } from '../constants/theme';
import { TransitProvider } from '../context/TransitContext';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { AccessSession, loadSession as loadAccessSession, onSessionChange as onAccessSessionChange } from '../services/accessApi';
import { ArrivalReveal } from '../components/access/ArrivalReveal';
import { TransitionHost } from '../components/access/BusTransition';

/**
 * Phase 41: sends commuters to the auth landing before the main tabs unless they are signed in or
 * explicitly chose guest (demo) mode. Crew/diagnostic screens (conductor, operations) are not gated.
 */
function AuthGate() {
  const { authReady, session, guestMode } = useAuth();
  const segments = useSegments();
  const router = useRouter();
  // The Access module account is the single ನಮ್ಮ Bus sign-in; the older session / guest mode still work
  const [accessSession, setAccessSession] = useState<AccessSession | null | undefined>(undefined);

  useEffect(() => {
    loadAccessSession().then(setAccessSession);
    return onAccessSessionChange(setAccessSession);
  }, []);

  useEffect(() => {
    if (!authReady || accessSession === undefined) return;
    const inTabs = segments[0] === '(tabs)' || (segments as string[]).length === 0;
    if (inTabs && !session && !guestMode && !accessSession) {
      router.replace('/access' as any);
    }
  }, [authReady, session, guestMode, accessSession, segments, router]);

  return null;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <AuthProvider>
        <TransitProvider>
          <AuthGate />
          <ArrivalReveal>
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: COLORS.background },
              animation: 'slide_from_right',
            }}
          >
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="auth" options={{ headerShown: false, gestureEnabled: false }} />
            <Stack.Screen name="conductor" options={{ headerShown: false, presentation: 'card' }} />
            <Stack.Screen name="login" options={{ headerShown: false, presentation: 'card' }} />
            <Stack.Screen name="identity-verify" options={{ headerShown: false, presentation: 'card' }} />
            <Stack.Screen name="operations" options={{ headerShown: false, presentation: 'card' }} />
            <Stack.Screen name="access" options={{ headerShown: false }} />
          </Stack>
          </ArrivalReveal>
          {/* Sign-in bus transition overlay (above every screen, never blocks touches) */}
          <TransitionHost />
        </TransitProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
