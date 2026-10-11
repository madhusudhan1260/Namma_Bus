import React, { useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { PickedFile } from '../../services/accessApi';
import { CameraCapture } from './CameraCapture';

/** Native: photograph the document with the camera (no extra file-picker dependency needed). */
export function DocumentPicker({ label, file, onPicked }: { label: string; file: PickedFile | null; onPicked: (f: PickedFile) => void; onError: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  if (open) {
    return (
      <CameraCapture
        facing="back"
        purpose={`The camera is used only to photograph your ${label}. The photo is uploaded securely and not saved on this device.`}
        captureLabel={`Photograph ${label}`}
        onCaptured={f => {
          onPicked(f);
          setOpen(false);
        }}
        onCancel={() => setOpen(false)}
      />
    );
  }
  return (
    <TouchableOpacity style={styles.box} onPress={() => setOpen(true)} accessibilityRole="button" accessibilityLabel={`Photograph ${label}`}>
      <Ionicons name={file ? 'document-attach' : 'camera-outline'} size={22} color={COLORS.deepNavy} />
      <View style={{ flex: 1, marginLeft: SPACING.sm }}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.sub}>{file ? 'Photo attached' : 'Take a clear photo'}</Text>
      </View>
      <Text style={styles.action}>{file ? 'Retake' : 'Open camera'}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', minHeight: 56, borderWidth: 1.5, borderStyle: 'dashed', borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  label: { fontWeight: '800', color: COLORS.textPrimary },
  sub: { fontSize: 12, color: COLORS.textSecondary },
  action: { fontWeight: '800', color: COLORS.primaryDark },
});
