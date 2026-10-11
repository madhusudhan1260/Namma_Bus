import { useRouter } from 'expo-router';
import { AccessSession } from '../../services/accessApi';

const TRAVELLER_PATHS = /^\/(access\/(buy|ticket|tickets|passenger|student|aadhaar|help|privacy)|\(tabs\)|map|tickets|more)?/;

/**
 * Sends a signed-in user to the right place: staff to their portal, travellers through any pending
 * onboarding step (decided by the backend), then back to where they were going (`next`) or Home.
 */
export function routeAfterLogin(router: ReturnType<typeof useRouter>, s: AccessSession, next?: string | null) {
  if (s.portal === 'conductor') return router.replace('/access/conductor' as any);
  if (s.portal === 'college') return router.replace('/access/college' as any);
  if (s.portal === 'admin') return router.replace('/access/admin' as any);
  if (s.next_step === 'AADHAAR_QUESTION' || s.next_step === 'IDENTITY_CONSENT') return router.replace('/access/aadhaar' as any);
  if (s.next_step === 'STUDENT_VERIFICATION') return router.replace('/access/student' as any);
  if (next && next.startsWith('/') && !next.startsWith('//') && TRAVELLER_PATHS.test(next) && next !== '/access') {
    return router.replace(next as any);
  }
  return router.replace('/(tabs)' as any);
}
