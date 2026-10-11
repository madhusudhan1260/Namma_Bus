/**
 * Phase 41: Auth, identity onboarding & Shakti eligibility API client.
 *
 * Unlike the transit endpoints, these calls have NO offline fallbacks: an identity or eligibility
 * result must never be fabricated on the device. Network failures surface as AuthApiError.
 */
import { API_BASE_URL } from './api';
import {
  AuthResponseDto,
  AuthUserDto,
  DigiLockerStatusDto,
  IdentityVerificationResultDto,
  IdentityVerificationStartDto,
  ShaktiEligibilityDto,
} from '../types/auth';

export class AuthApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T> {
  const { token, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(headers || {}),
      },
    });
  } catch {
    throw new AuthApiError(0, 'NETWORK');
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = String(body.detail[0].msg).replace(/^Value error, /, '');
    } catch {
      // keep HTTP status text
    }
    throw new AuthApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const AuthApi = {
  register(fullName: string, mobile: string, email: string, accountType: 'GENERAL' | 'SHAKTI_ONBOARDING') {
    return request<AuthResponseDto>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ full_name: fullName, mobile, email, account_type: accountType }),
    });
  },

  login(mobile: string) {
    return request<AuthResponseDto>('/auth/login', { method: 'POST', body: JSON.stringify({ mobile }) });
  },

  me(token: string) {
    return request<AuthUserDto>('/auth/me', { token });
  },

  updateProfile(token: string, changes: { full_name?: string; email?: string }) {
    return request<AuthUserDto>('/auth/profile', { method: 'PATCH', token, body: JSON.stringify(changes) });
  },

  logout(token: string) {
    return request<{ status: string; session_ended: boolean }>('/auth/logout', { method: 'POST', token });
  },

  startDigiLocker(token: string) {
    return request<DigiLockerStatusDto>('/identity/digilocker/start', { method: 'POST', token });
  },

  getDigiLockerStatus(token: string) {
    return request<DigiLockerStatusDto>('/identity/digilocker/status', { token });
  },

  startVerification(token: string, purpose: 'SHAKTI_ONBOARDING' | 'SHAKTI_TICKET', consentConfirmed: boolean) {
    return request<IdentityVerificationStartDto>('/identity/verification/start', {
      method: 'POST',
      token,
      body: JSON.stringify({ purpose, consent_confirmed: consentConfirmed }),
    });
  },

  completeVerification(token: string, attemptId: string, livenessActionCompleted: boolean) {
    return request<IdentityVerificationResultDto>('/identity/verification/complete', {
      method: 'POST',
      token,
      body: JSON.stringify({ attempt_id: attemptId, liveness_action_completed: livenessActionCompleted }),
    });
  },

  checkShaktiEligibility(token: string) {
    return request<ShaktiEligibilityDto>('/shakti/eligibility/check', { method: 'POST', token });
  },

  setDemoVerificationMode(enabled: boolean, demoOutcome: 'MATCH' | 'NO_MATCH' = 'MATCH') {
    return request<{ provider_mode: string; available: boolean; label: string | null; message: string }>(
      '/identity/verification/demo-mode',
      { method: 'POST', body: JSON.stringify({ enabled, demo_outcome: demoOutcome }) }
    );
  },
};
