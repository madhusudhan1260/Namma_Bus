import { Redirect } from 'expo-router';

/** Old simulated operations/demo-control screen → the Super Admin portal. */
export default function LegacyRedirect() {
  return <Redirect href={'/access/admin' as any} />;
}
