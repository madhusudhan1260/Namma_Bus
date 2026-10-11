import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { PickedFile } from '../../services/accessApi';

const MAX_BYTES = 5 * 1024 * 1024;

/** Web: native file dialog. The server re-checks type (by content), size and runs the scan hook. */
export function DocumentPicker({ label, file, onPicked, onError }: { label: string; file: PickedFile | null; onPicked: (f: PickedFile) => void; onError: (m: string) => void }) {
  const pick = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf,image/jpeg,image/png';
    input.onchange = () => {
      const f = input.files?.[0];
      if (!f) return;
      if (f.size > MAX_BYTES) return onError(`${label}: file is larger than 5 MB.`);
      onPicked({ name: f.name, type: f.type || 'application/octet-stream', blob: f });
    };
    input.click();
  };
  return (
    <TouchableOpacity style={styles.box} onPress={pick} accessibilityRole="button" accessibilityLabel={`Upload ${label}`}>
      <Ionicons name={file ? 'document-attach' : 'cloud-upload-outline'} size={22} color={COLORS.deepNavy} />
      <View style={{ flex: 1, marginLeft: SPACING.sm }}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.sub} numberOfLines={1}>{file ? file.name : 'PDF, JPEG or PNG · max 5 MB'}</Text>
      </View>
      <Text style={styles.action}>{file ? 'Change' : 'Choose'}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', minHeight: 56, borderWidth: 1.5, borderStyle: 'dashed', borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  label: { fontWeight: '800', color: COLORS.textPrimary },
  sub: { fontSize: 12, color: COLORS.textSecondary },
  action: { fontWeight: '800', color: COLORS.primaryDark },
});
