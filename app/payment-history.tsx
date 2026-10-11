import { Redirect } from 'expo-router';

/** Old payment history → My tickets. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/tickets' as any} />;
}
