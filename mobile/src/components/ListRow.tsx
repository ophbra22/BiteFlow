import { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { colors, radius, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, IconName, directional } from './Icon';

type Props = {
  title: string;
  hint?: string;
  icon?: IconName;
  /** A short value at the far edge, such as the current language. */
  value?: string;
  /** Replaces the chevron, for a switch or a spinner. */
  trailing?: ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  destructive?: boolean;
  /** Set on every row but the first in a group. */
  divider?: boolean;
  testID?: string;
  accessibilityHint?: string;
};

/** A row in a grouped list. Icon and chevron swap sides with the reading direction. */
export function ListRow({
  title,
  hint,
  icon,
  value,
  trailing,
  onPress,
  disabled,
  destructive,
  divider,
  testID,
  accessibilityHint,
}: Props) {
  const tint = destructive ? colors.danger : colors.sand;
  const body = (
    <>
      {icon ? (
        <View style={[styles.badge, destructive && styles.badgeDanger]}>
          <Icon name={icon} size={20} color={destructive ? colors.danger : colors.sage} />
        </View>
      ) : null}
      <View style={styles.text}>
        <AppText variant="bodyStrong" color={tint}>
          {title}
        </AppText>
        {hint ? (
          <AppText variant="caption" color={colors.muted}>
            {hint}
          </AppText>
        ) : null}
      </View>
      {value ? (
        <AppText variant="label" color={colors.muted}>
          {value}
        </AppText>
      ) : null}
      {trailing ?? (onPress ? <Icon name={directional.forward} size={20} color={colors.muted} /> : null)}
    </>
  );
  if (!onPress) return <View style={[styles.row, divider && styles.divider]}>{body}</View>;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={value ? `${title}, ${value}` : title}
      accessibilityHint={accessibilityHint ?? hint}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        divider && styles.divider,
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}>
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    minHeight: touch + spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  pressed: { backgroundColor: colors.field },
  disabled: { opacity: 0.45 },
  badge: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.sageTint,
  },
  badgeDanger: { backgroundColor: colors.dangerTint },
  text: { flex: 1, gap: 2 },
});
