/**
 * Short tactile confirmations. Feedback is never required: unsupported devices,
 * the web preview and a user's system setting simply produce nothing.
 */
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

const quietly = (play: () => Promise<void>) => {
  if (Platform.OS === 'web') return;
  try {
    void play().catch(() => undefined);
  } catch {
    // A missing native module must not interrupt the user's action.
  }
};

export const haptics = {
  /** A selection moved: a segment, a chip. */
  selection: () => quietly(() => Haptics.selectionAsync()),
  /** A small action took effect: water added, an item confirmed. */
  tap: () => quietly(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)),
  /** A task finished: a meal saved, a code scanned. */
  success: () => quietly(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)),
  /** Something needs attention before continuing. */
  warning: () => quietly(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)),
};
