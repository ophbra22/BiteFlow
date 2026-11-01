import { Pressable, StyleSheet, View } from 'react-native';

import { haptics } from '@/native/haptics';
import { colors, radius, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';

type Option<T extends string> = { value: T; label: string; dot?: string };

type Props<T extends string> = {
  label: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
};

/**
 * A small set of exclusive choices. Up to three share one track, like the native
 * segmented control; longer sets keep two per row. Wraps with large text.
 */
export function Segmented<T extends string>({ label, options, value, onChange, disabled }: Props<T>) {
  const inline = options.length <= 3;
  return (
    <View style={styles.wrap} accessibilityRole="radiogroup" accessibilityLabel={label}>
      <AppText variant="label" color={colors.muted}>
        {label}
      </AppText>
      <View style={[styles.row, inline && styles.track]}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={option.value}
              accessibilityRole="radio"
              accessibilityLabel={option.label}
              accessibilityState={{ selected, disabled: !!disabled }}
              disabled={disabled}
              onPress={() => {
                if (!selected) haptics.selection();
                onChange(option.value);
              }}
              style={[
                styles.item,
                inline && styles.itemInline,
                selected && styles.selected,
                disabled && styles.disabled,
              ]}>
              {option.dot ? <View style={[styles.dot, { backgroundColor: option.dot }]} /> : null}
              <AppText
                variant="label"
                center
                color={selected ? colors.ground : colors.sand}
                style={styles.text}>
                {option.label}
              </AppText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs + 2 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  track: { backgroundColor: colors.field, borderRadius: radius.md, padding: 4, gap: 4 },
  item: {
    flexGrow: 1,
    // Two per row: "Breakfast" and the Hebrew meal names never break mid-word.
    flexBasis: '40%',
    minHeight: touch,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs + 2,
    borderRadius: radius.md,
    backgroundColor: colors.field,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  itemInline: { flexBasis: '30%', backgroundColor: 'transparent', minHeight: touch, borderRadius: radius.sm },
  selected: { backgroundColor: colors.sand },
  disabled: { opacity: 0.55 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  text: { flexShrink: 1 },
});
