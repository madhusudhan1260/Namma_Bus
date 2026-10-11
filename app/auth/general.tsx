import { Redirect } from 'expo-router';

/** Old Phase 41 sign-in → the single ನಮ್ಮ Bus sign-in. */
export default function LegacyRedirect() {
  return <Redirect href={'/access' as any} />;
}
