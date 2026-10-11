import { PickedFile } from '../../services/accessApi';

/**
 * Native builds have no file picker yet (expo-document-picker is not installed), so the Aadhaar file is uploaded
 * from the web app. The screen shows a notice instead of this control.
 */
export function AadhaarFilePicker(_props: {
  label: string; hint: string; dropHint: string; file: PickedFile | null; onPicked: (f: PickedFile) => void; onError: (m: string) => void;
}) {
  return null;
}

export const AADHAAR_PICKER_SUPPORTED = false;
