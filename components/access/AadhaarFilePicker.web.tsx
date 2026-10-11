import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, RADIUS, SPACING } from '../../constants/theme';
import { PickedFile } from '../../services/accessApi';

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = '.pdf,.zip,application/pdf,application/zip,application/x-zip-compressed';

/**
 * Web: choose or drag & drop the UIDAI e-Aadhaar PDF or Offline e-KYC ZIP. The server verifies UIDAI's
 * digital signature; nothing about the file is trusted here.
 */
export function AadhaarFilePicker({ label, hint, dropHint, file, onPicked, onError }: {
  label: string; hint: string; dropHint: string; file: PickedFile | null; onPicked: (f: PickedFile) => void; onError: (m: string) => void;
}) {
  const ref = useRef<any>(null);
  const [over, setOver] = useState(false);

  const accept = (f?: File | null) => {
    if (!f) return;
    const kind = /\.pdf$/i.test(f.name) || f.type === 'application/pdf' ? 'pdf' : /\.zip$/i.test(f.name) ? 'zip' : null;
    if (!kind) return onError(`${label}: choose the e-Aadhaar PDF or the Offline e-KYC .zip from UIDAI.`);
    if (f.size > MAX_BYTES) return onError(`${label}: file is larger than 5 MB.`);
    onPicked({ name: f.name, type: kind === 'pdf' ? 'application/pdf' : 'application/zip', blob: f });
  };

  const pick = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = ACCEPT;
    input.onchange = () => accept(input.files?.[0]);
    input.click();
  };

  useEffect(() => {
    const el: HTMLElement | null = ref.current;
    if (!el || typeof el.addEventListener !== 'function') return;
    const stop = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    };
    const enter = (e: DragEvent) => {
      stop(e);
      setOver(true);
    };
    const leave = (e: DragEvent) => {
      stop(e);
      setOver(false);
    };
    const drop = (e: DragEvent) => {
      stop(e);
      setOver(false);
      accept(e.dataTransfer?.files?.[0]);
    };
    el.addEventListener('dragenter', enter);
    el.addEventListener('dragover', enter);
    el.addEventListener('dragleave', leave);
    el.addEventListener('drop', drop);
    return () => {
      el.removeEventListener('dragenter', enter);
      el.removeEventListener('dragover', enter);
      el.removeEventListener('dragleave', leave);
      el.removeEventListener('drop', drop);
    };
  });

  return (
    <View ref={ref} style={[styles.zone, over && styles.zoneOver]}>
      <TouchableOpacity style={styles.inner} onPress={pick} accessibilityRole="button" accessibilityLabel={`Upload ${label}`}>
        <Ionicons name={file ? 'document-lock' : over ? 'download-outline' : 'cloud-upload-outline'} size={28} color={COLORS.deepNavy} />
        <Text style={styles.label}>{file ? file.name : over ? dropHint : label}</Text>
        <Text style={styles.sub}>{file ? hint : `${dropHint} · ${hint}`}</Text>
        <Text style={styles.action}>{file ? 'Change file' : 'Choose file'}</Text>
      </TouchableOpacity>
    </View>
  );
}

export const AADHAAR_PICKER_SUPPORTED = true;

const styles = StyleSheet.create({
  zone: { borderWidth: 2, borderStyle: 'dashed', borderColor: COLORS.border, borderRadius: RADIUS.lg, marginBottom: SPACING.md, backgroundColor: COLORS.surface },
  zoneOver: { borderColor: COLORS.primaryDark, backgroundColor: '#EEF4FF' },
  inner: { alignItems: 'center', paddingVertical: SPACING.lg, paddingHorizontal: SPACING.md, minHeight: 140, justifyContent: 'center' },
  label: { fontWeight: '800', color: COLORS.textPrimary, marginTop: 6, textAlign: 'center' },
  sub: { fontSize: 12, color: COLORS.textSecondary, marginTop: 4, textAlign: 'center' },
  action: { fontWeight: '800', color: COLORS.primaryDark, marginTop: 8 },
});
