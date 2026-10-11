import React, { useRef, useState } from 'react';
import { Linking, Platform, StyleSheet, Text, View } from 'react-native';
import { CameraView } from 'expo-camera';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { requestCameraPermission } from '../../services/faceVerification';
import { PickedFile } from '../../services/accessApi';
import { CameraPermissionState } from '../../types/auth';
import { AuthButton, Notice } from '../auth/AuthUi';

/**
 * Takes one photo after the user has consented and granted camera permission. The photo is handed to the
 * caller for immediate upload; it is not saved to the gallery or kept by the app.
 */
export function CameraCapture({
  facing,
  purpose,
  captureLabel,
  onCaptured,
  onCancel,
}: {
  facing: 'front' | 'back';
  purpose: string;
  captureLabel: string;
  onCaptured: (file: PickedFile) => void;
  onCancel: () => void;
}) {
  const [perm, setPerm] = useState<CameraPermissionState>('UNKNOWN');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cam = useRef<CameraView>(null);

  const allow = async () => {
    setBusy(true);
    setPerm(await requestCameraPermission());
    setBusy(false);
  };

  const capture = async () => {
    if (!cam.current) return;
    setBusy(true);
    setError(null);
    try {
      const pic = await cam.current.takePictureAsync({ quality: 0.6, skipProcessing: true });
      if (!pic?.uri) throw new Error('No image');
      const name = `capture-${Date.now()}.jpg`;
      if (Platform.OS === 'web') {
        const blob = await (await fetch(pic.uri)).blob();
        onCaptured({ name, type: blob.type || 'image/jpeg', blob });
      } else {
        onCaptured({ name, type: 'image/jpeg', uri: pic.uri });
      }
    } catch {
      setError('The photo could not be taken. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (perm !== 'GRANTED') {
    return (
      <View>
        <Notice tone="info" title="Camera permission" body={purpose} />
        {perm === 'DENIED' || perm === 'BLOCKED' ? <Notice tone="warning" body="Camera access was not allowed." /> : null}
        {perm === 'UNAVAILABLE' ? <Notice tone="warning" body="No camera is available on this device." /> : null}
        {perm === 'BLOCKED' ? (
          <AuthButton icon="settings-outline" label="Open settings" onPress={() => Linking.openSettings()} />
        ) : perm !== 'UNAVAILABLE' ? (
          <AuthButton icon="camera-outline" label="Allow camera" onPress={allow} loading={busy} />
        ) : null}
        <AuthButton variant="link" label="Cancel" onPress={onCancel} />
      </View>
    );
  }

  return (
    <View>
      <View style={styles.frame}>
        <CameraView ref={cam} style={StyleSheet.absoluteFill} facing={facing} active />
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <AuthButton icon="camera" label={captureLabel} onPress={capture} loading={busy} />
      <AuthButton variant="link" label="Cancel" onPress={onCancel} />
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { height: 300, borderRadius: RADIUS.lg, overflow: 'hidden', backgroundColor: '#000', marginBottom: SPACING.md },
  error: { color: COLORS.error, marginBottom: SPACING.sm },
});
