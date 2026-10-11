/**
 * Phase 41: Client-side face / liveness verification architecture.
 *
 * FaceVerificationProvider mirrors the backend contract:
 *   startVerification() -> captureLivenessFrame() -> verify() -> clearTemporaryCapture()
 *
 * The current implementation (BackendFaceVerificationProvider) never captures, stores or uploads an
 * image. The camera preview is shown only for positioning guidance; "capture" records that the
 * commuter explicitly performed the liveness action. When an authorized provider SDK is integrated,
 * its captureLivenessFrame() must hand the frame straight to that SDK and clearTemporaryCapture()
 * must delete it. No face matching or embedding is ever done in this app.
 */
import { Camera, CameraView } from 'expo-camera';
import { AuthApi } from './authApi';
import {
  CameraPermissionState,
  IdentityVerificationResultDto,
  IdentityVerificationStartDto,
} from '../types/auth';

export interface FaceVerificationProvider {
  startVerification(purpose: 'SHAKTI_ONBOARDING' | 'SHAKTI_TICKET', consentConfirmed: boolean): Promise<IdentityVerificationStartDto>;
  captureLivenessFrame(): void;
  verify(): Promise<IdentityVerificationResultDto>;
  clearTemporaryCapture(): void;
}

export class BackendFaceVerificationProvider implements FaceVerificationProvider {
  private attemptId: string | null = null;
  private livenessConfirmed = false;

  constructor(private readonly token: string) {}

  async startVerification(purpose: 'SHAKTI_ONBOARDING' | 'SHAKTI_TICKET', consentConfirmed: boolean) {
    this.clearTemporaryCapture();
    const res = await AuthApi.startVerification(this.token, purpose, consentConfirmed);
    this.attemptId = res.available ? res.attempt_id : null;
    return res;
  }

  /** Called only from an explicit user action ("I have done this"). Captures no image. */
  captureLivenessFrame() {
    this.livenessConfirmed = true;
  }

  async verify() {
    if (!this.attemptId) {
      throw new Error('Verification has not been started.');
    }
    try {
      return await AuthApi.completeVerification(this.token, this.attemptId, this.livenessConfirmed);
    } finally {
      this.clearTemporaryCapture();
    }
  }

  clearTemporaryCapture() {
    this.attemptId = null;
    this.livenessConfirmed = false;
  }
}

function mapPermission(res: { granted: boolean; canAskAgain: boolean; status: string }): CameraPermissionState {
  if (res.granted) return 'GRANTED';
  if (res.status === 'denied' && !res.canAskAgain) return 'BLOCKED';
  if (res.status === 'denied') return 'DENIED';
  return 'UNKNOWN';
}

/** Reads the current camera permission without prompting. */
export async function getCameraPermissionState(): Promise<CameraPermissionState> {
  try {
    const available = await CameraView.isAvailableAsync();
    if (!available) return 'UNAVAILABLE';
    return mapPermission(await Camera.getCameraPermissionsAsync());
  } catch {
    return 'UNAVAILABLE';
  }
}

/** Prompts for camera permission. Only call after the commuter taps "Allow Camera". */
export async function requestCameraPermission(): Promise<CameraPermissionState> {
  try {
    const available = await CameraView.isAvailableAsync();
    if (!available) return 'UNAVAILABLE';
    const state = mapPermission(await Camera.requestCameraPermissionsAsync());
    return state === 'UNKNOWN' ? 'DENIED' : state;
  } catch {
    return 'UNAVAILABLE';
  }
}
