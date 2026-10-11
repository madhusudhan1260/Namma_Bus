import React, { useRef, useState } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import { CameraView } from 'expo-camera';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { requestCameraPermission } from '../../services/faceVerification';
import { CameraPermissionState } from '../../types/auth';
import { AuthButton, Notice, useAuthStrings } from '../auth/AuthUi';

interface Props {
  onScan: (data: string) => void;
  onClose: () => void;
}

/**
 * Phase 45: conductor ticket QR scanning with expo-camera.
 * The camera opens only after "Allow Camera"; frames are decoded on the device and never stored.
 * The same code is ignored for 3 seconds to avoid duplicate scans while the ticket is held in view.
 */
export function TicketQrScanner({ onScan, onClose }: Props) {
  const { tr } = useAuthStrings();
  const [perm, setPerm] = useState<CameraPermissionState>('UNKNOWN');
  const [busy, setBusy] = useState(false);
  const last = useRef<{ data: string; at: number } | null>(null);

  const allow = async () => {
    setBusy(true);
    setPerm(await requestCameraPermission());
    setBusy(false);
  };

  if (perm !== 'GRANTED') {
    return (
      <View style={styles.box}>
        <Notice tone="info" title={tr('cameraPermissionTitle')} body={tr('scanCameraPurpose')} />
        {perm === 'DENIED' ? <Notice tone="warning" body={tr('cameraDenied')} /> : null}
        {perm === 'BLOCKED' ? <Notice tone="warning" body={tr('cameraBlocked')} /> : null}
        {perm === 'UNAVAILABLE' ? <Notice tone="warning" body={tr('cameraUnavailable')} /> : null}
        {perm === 'BLOCKED' ? (
          <AuthButton icon="settings-outline" label={tr('cameraOpenSettings')} onPress={() => Linking.openSettings()} />
        ) : perm !== 'UNAVAILABLE' ? (
          <AuthButton icon="camera-outline" label={tr('cameraAllow')} onPress={allow} loading={busy} />
        ) : null}
        <AuthButton variant="link" label={tr('cameraCancel')} onPress={onClose} />
      </View>
    );
  }

  return (
    <View style={styles.box}>
      <Text style={styles.instructions} accessibilityLiveRegion="polite">{tr('scanInstructions')}</Text>
      <View style={styles.preview} accessible accessibilityLabel={tr('scanInstructions')}>
        <CameraView
          style={StyleSheet.absoluteFill}
          facing="back"
          active
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={({ data }) => {
            const now = Date.now();
            if (last.current && last.current.data === data && now - last.current.at < 3000) return;
            last.current = { data, at: now };
            onScan(data);
          }}
        />
        <View style={styles.frame} pointerEvents="none" />
      </View>
      <Text style={styles.note}>{tr('scanCameraPurpose')}</Text>
      <AuthButton variant="secondary" icon="stop-circle-outline" label={tr('scanStop')} onPress={onClose} />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { marginTop: SPACING.md },
  instructions: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary, marginBottom: SPACING.sm },
  preview: { height: 260, borderRadius: RADIUS.lg, overflow: 'hidden', backgroundColor: '#0F172A', alignItems: 'center', justifyContent: 'center' },
  frame: { width: 180, height: 180, borderWidth: 3, borderColor: COLORS.textInverse, borderRadius: RADIUS.md },
  note: { fontSize: 12, color: COLORS.textMuted, marginTop: SPACING.sm },
});
