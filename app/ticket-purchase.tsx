import { Redirect } from 'expo-router';

/** Old ticket purchase → the real ticket purchase flow. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/buy' as any} />;
}
