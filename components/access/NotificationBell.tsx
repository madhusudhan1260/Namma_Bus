import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { COLORS } from '../../constants/theme';
import { useAccessT } from '../../constants/accessI18n';
import { useNotifications } from '../../hooks/useNotifications';

/** Bell with the live unread count. Renders nothing when nobody is signed in. */
export function NotificationBell({ tint = COLORS.deepNavy, background = '#FFFFFF' }: { tint?: string; background?: string }) {
  const router = useRouter();
  const { a } = useAccessT();
  const { signedIn, unread } = useNotifications();
  if (!signedIn) return null;
  const label = unread ? `${a('notifTitle')}: ${unread}` : a('notifTitle');
  return (
    <TouchableOpacity onPress={() => router.push('/notifications' as any)} style={[styles.btn, { backgroundColor: background }]}
      accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={unread ? 'notifications' : 'notifications-outline'} size={20} color={tint} />
      {unread ? (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{unread > 9 ? '9+' : unread}</Text>
        </View>
      ) : null}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  badge: { position: 'absolute', top: 4, right: 3, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: '#E0262E',
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4, borderWidth: 2, borderColor: '#FFFFFF' },
  badgeText: { color: '#FFFFFF', fontSize: 10, fontWeight: '900' },
});
