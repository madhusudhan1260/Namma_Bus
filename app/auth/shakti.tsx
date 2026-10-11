import { Redirect } from 'expo-router';

/** Old demo Shakti sign-up → registration with verified eligibility. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/register' as any} />;
}
