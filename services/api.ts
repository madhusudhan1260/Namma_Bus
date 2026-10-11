/**
 * Backend address for the ನಮ್ಮ Bus API. All data clients (accessApi, networkApi, authApi) build on this.
 * The old simulated-corridor client (fake buses, journeys, alerts, demo controls) has been removed.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';

const getBaseUrl = (): string => {
  // 1. Explicit environment variable override takes top priority (e.g. EXPO_PUBLIC_API_URL=http://192.168.1.x:8001/api)
  const envUrl = process.env.EXPO_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }

  // 2. Web browser: standard localhost
  if (Platform.OS === 'web') {
    return 'http://localhost:8001/api';
  }

  // 3. Android emulator
  if (Platform.OS === 'android') {
    return 'http://10.0.2.2:8001/api';
  }

  // 4. Physical device via Expo Go (auto-resolves host Mac LAN IP from Metro connection)
  const hostUri = Constants.expoConfig?.hostUri || (Constants as any).manifest2?.extra?.expoClient?.hostUri;
  if (hostUri) {
    const host = hostUri.split(':')[0];
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return `http://${host}:8001/api`;
    }
  }

  // 5. Default fallback (iOS Simulator)
  return 'http://localhost:8001/api';
};

export const API_BASE_URL = getBaseUrl();
