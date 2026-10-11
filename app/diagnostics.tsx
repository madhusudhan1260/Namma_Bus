import { Redirect } from 'expo-router';

/** Simulated diagnostics removed. */
export default function LegacyRedirect() {
  return <Redirect href={'/(tabs)/more' as any} />;
}
