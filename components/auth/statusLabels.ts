import { Ionicons } from '@expo/vector-icons';
import { TranslationKey } from '../../constants/i18n';
import { AccountIdentityStatus, ShaktiEligibilityStatus } from '../../types/auth';

type StatusView = { key: TranslationKey; icon: keyof typeof Ionicons.glyphMap; tone: 'success' | 'warning' | 'error' | 'info' | 'demo' };

// Every status pairs text with an icon so meaning never relies on colour alone.
export const IDENTITY_STATUS_VIEW: Record<AccountIdentityStatus, StatusView> = {
  NOT_STARTED: { key: 'identityStatusNotStarted', icon: 'ellipse-outline', tone: 'info' },
  IN_PROGRESS: { key: 'identityStatusInProgress', icon: 'time-outline', tone: 'info' },
  AUTHORIZED_VERIFIED: { key: 'identityStatusAuthorized', icon: 'shield-checkmark', tone: 'success' },
  DEMO_VERIFIED: { key: 'identityStatusDemo', icon: 'flask', tone: 'demo' },
  FAILED: { key: 'identityStatusFailed', icon: 'close-circle', tone: 'error' },
  UNAVAILABLE: { key: 'identityStatusUnavailable', icon: 'cloud-offline-outline', tone: 'warning' },
};

export const SHAKTI_STATUS_VIEW: Record<ShaktiEligibilityStatus, StatusView> = {
  ELIGIBLE: { key: 'shaktiEligible', icon: 'checkmark-circle', tone: 'success' },
  DEMO_ELIGIBLE: { key: 'shaktiDemoEligible', icon: 'flask', tone: 'demo' },
  NOT_VERIFIED: { key: 'shaktiNotVerified', icon: 'ellipse-outline', tone: 'info' },
  VERIFICATION_UNAVAILABLE: { key: 'shaktiVerificationUnavailable', icon: 'cloud-offline-outline', tone: 'warning' },
  NOT_ELIGIBLE: { key: 'shaktiNotEligible', icon: 'remove-circle-outline', tone: 'error' },
};
