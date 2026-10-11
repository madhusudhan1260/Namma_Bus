import { Stack } from 'expo-router';

/** Access module screens (accounts, eligibility, student/college/conductor/admin portals). */
export default function AccessLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }} />;
}
