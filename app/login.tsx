import { Redirect } from 'expo-router';

/** Old demo login → the single ನಮ್ಮ Bus sign-in. */
export default function LegacyRedirect() {
  return <Redirect href={'/access' as any} />;
}
