import { Pressable, StyleSheet } from 'react-native';

import { haptics } from '@/native/haptics';
import { colors, radius, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, IconName } from './Icon';

type Props = {
  label: string;
  onPress: () => void;
  selected?: boolean;
  icon?: IconName;
  disabled?: boolean;
  /** Selected means "this layer is on", not "this one of several". */
  toggle?: boolean;
  /** One of a mutually exclusive set. */
  radio?: boolean;
  testID?: string;
};

/** A small, tappable choice or quick action. Its touch area stays 48 points tall. */
export function Chip({ label, onPress, selected, icon, disabled, toggle, radio, testID }: Props) {
  const fg = selected ? colors.ground : colors.sand;
  return (
    <Pressable
      testID={testID}
      accessibilityRole={radio ? 'radio' : toggle ? 'switch' : 'button'}
      accessibilityLabel={label}
      accessibilityState={{
        disabled: !!disabled,
        selected: !!selected,
        ...(toggle ? { checked: !!selected } : null),
      }}
      disabled={disabled}
      hitSlop={{ top: 4, bottom: 4 }}
      onPress={() => {
        if (radio || toggle) haptics.selection();
        onPress();
      }}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.selected,
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}>
      {icon ? <Icon name={icon} size={16} color={fg} /> : null}
      <AppText variant="label" color={fg} style={styles.label}>
        {label}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    alignSelf: 'flex-start',
    minHeight: touch - 8,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs + 2,
    borderRadius: radius.pill,
    backgroundColor: colors.field,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  selected: { backgroundColor: colors.sand },
  pressed: { opacity: 0.75 },
  disabled: { opacity: 0.45 },
  label: { flexShrink: 1 },
});
