import { Redirect } from 'expo-router';

/** Old payment screen → My tickets (payment happens on the ticket). */
export default function LegacyRedirect() {
  return <Redirect href={'/access/tickets' as any} />;
}
