import { StyleSheet } from 'react-native';
import { COLORS, SPACING } from '../../constants/theme';

/** Shared layout for the coloured-header feature screens (Time Table, Fare Calculator, User Guide). */
export const screenStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  header: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: SPACING.md, paddingVertical: 14 },
  back: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.18)' },
  headerTitle: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
  body: { padding: SPACING.md, width: '100%', maxWidth: 760, alignSelf: 'center', paddingBottom: 40 },
});
