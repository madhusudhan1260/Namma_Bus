import { Redirect } from 'expo-router';

/** Old demo identity screen → the identity verification flow. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/aadhaar' as any} />;
}
