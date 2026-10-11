import { Redirect } from 'expo-router';

/** Old demo conductor screen → the real conductor portal. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/conductor' as any} />;
}
