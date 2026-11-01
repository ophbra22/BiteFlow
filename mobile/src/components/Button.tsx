import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { colors, radius, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, IconName } from './Icon';

type Kind = 'primary' | 'secondary' | 'ghost' | 'danger';

type Props = {
  label: string;
  onPress: () => void;
  kind?: Kind;
  icon?: IconName;
  disabled?: boolean;
  /** Shows a spinner and blocks further taps. */
  busy?: boolean;
  busyLabel?: string;
  accessibilityHint?: string;
  testID?: string;
  /** A shorter button for secondary rows; the touch target stays at least 48 points. */
  compact?: boolean;
};

const palette: Record<Kind, { bg: string; fg: string; border?: string }> = {
  primary: { bg: colors.sage, fg: colors.onSage },
  secondary: { bg: colors.field, fg: colors.sand },
  ghost: { bg: 'transparent', fg: colors.sage },
  danger: { bg: 'transparent', fg: colors.danger, border: colors.danger },
};

export function Button({
  label,
  onPress,
  kind = 'primary',
  icon,
  disabled,
  busy,
  busyLabel,
  accessibilityHint,
  testID,
  compact,
}: Props) {
  const tone = palette[kind];
  const blocked = disabled || busy;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={busy && busyLabel ? busyLabel : label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!blocked, busy: !!busy }}
      disabled={blocked}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        compact && styles.compact,
        { backgroundColor: tone.bg, borderColor: tone.border ?? 'transparent' },
        pressed && styles.pressed,
        disabled && !busy && styles.disabled,
      ]}>
      <View style={styles.content}>
        {busy ? (
          <ActivityIndicator color={tone.fg} />
        ) : icon ? (
          <Icon name={icon} color={tone.fg} size={20} />
        ) : null}
        <AppText variant="bodyStrong" color={tone.fg} center style={styles.label}>
          {busy && busyLabel ? busyLabel : label}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 56,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    justifyContent: 'center',
  },
  compact: { minHeight: 48, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  content: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  label: { flexShrink: 1 },
  pressed: { opacity: 0.85, transform: [{ scale: 0.98 }] },
  disabled: { opacity: 0.45 },
});
