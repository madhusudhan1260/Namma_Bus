import { Platform } from 'react-native';
import * as Haptics from 'expo-haptics';

/** Small tactile confirmations on phones (no-op on web). Never blocks or throws. */
export const haptic = {
  tap: () => {
    if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
  },
  success: () => {
    if (Platform.OS !== 'web') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
  },
  warning: () => {
    if (Platform.OS !== 'web') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => undefined);
  },
  error: () => {
    if (Platform.OS !== 'web') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => undefined);
  },
};
