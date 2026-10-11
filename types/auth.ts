// Phase 41: Commuter authentication, identity onboarding & Shakti eligibility types.
// None of these types carry raw Aadhaar numbers, images, embeddings or passwords.

export type AccountType = 'GENERAL' | 'SHAKTI_ONBOARDING';

export type VerificationProviderMode = 'AUTHORIZED_VERIFICATION' | 'DEMO_VERIFICATION' | 'UNAVAILABLE';

export type AccountIdentityStatus =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'AUTHORIZED_VERIFIED'
  | 'DEMO_VERIFIED'
  | 'FAILED'
  | 'UNAVAILABLE';

export type FaceVerificationOutcome = 'MATCH' | 'NO_MATCH' | 'UNAVAILABLE' | 'VERIFICATION_ERROR';

export type ShaktiEligibilityStatus =
  | 'ELIGIBLE'
  | 'DEMO_ELIGIBLE'
  | 'NOT_VERIFIED'
  | 'VERIFICATION_UNAVAILABLE'
  | 'NOT_ELIGIBLE';

export type DigiLockerLinkStatus = 'NOT_LINKED' | 'PENDING_AUTHORIZATION' | 'LINKED' | 'UNAVAILABLE';

export type CameraPermissionState = 'UNKNOWN' | 'GRANTED' | 'DENIED' | 'BLOCKED' | 'UNAVAILABLE';

export interface AuthUserDto {
  user_id: string;
  display_name: string;
  masked_mobile: string;
  email: string;
  email_verification_status: 'NOT_CONNECTED' | 'PENDING' | 'VERIFIED';
  account_type: AccountType;
  identity_status: AccountIdentityStatus;
  verification_provider: VerificationProviderMode;
  masked_identity_suffix: string | null;
  shakti_eligibility_status: ShaktiEligibilityStatus;
  digilocker_status: DigiLockerLinkStatus;
  created_at: string;
  last_login_at: string;
}

export interface AuthResponseDto {
  session_token: string;
  user: AuthUserDto;
  authentication_assurance: 'UNVERIFIED_DEMO_CONTINUATION' | 'EMAIL_VERIFIED';
  email_verification_message: string;
}

export interface AuthSession {
  token: string;
  user: AuthUserDto;
}

export interface DigiLockerStatusDto {
  status: DigiLockerLinkStatus;
  provider_mode: VerificationProviderMode;
  configured: boolean;
  authorization_url: string | null;
  message: string;
  explanation: string;
}

export interface IdentityVerificationStartDto {
  attempt_id: string | null;
  provider_mode: VerificationProviderMode;
  available: boolean;
  liveness_actions: string[];
  message: string;
  label: string | null;
}

export interface IdentityVerificationResultDto {
  attempt_id: string | null;
  outcome: FaceVerificationOutcome;
  provider_mode: VerificationProviderMode;
  identity_status: AccountIdentityStatus;
  shakti_eligibility_status: ShaktiEligibilityStatus;
  masked_identity_suffix: string | null;
  temporary_capture_cleared: boolean;
  message: string;
  label: string | null;
  verified_at: string | null;
}

export interface ShaktiEligibilityDto {
  eligibility_status: ShaktiEligibilityStatus;
  concession_allowed: boolean;
  requires_verification: boolean;
  verification_fresh: boolean;
  provider_mode: VerificationProviderMode;
  label: string | null;
  message: string;
  checked_at: string;
}
