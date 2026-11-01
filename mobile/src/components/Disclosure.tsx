import { ReactNode, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { colors, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon } from './Icon';

type Props = { label: string; children: ReactNode; initiallyOpen?: boolean; testID?: string };

/** Keeps optional or rarely used controls one tap away instead of on the screen. */
export function Disclosure({ label, children, initiallyOpen = false, testID }: Props) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <View style={styles.wrap}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((value) => !value)}
        style={({ pressed }) => [styles.head, pressed && styles.pressed]}>
        <AppText variant="label" color={colors.sage} style={styles.label}>
          {label}
        </AppText>
        <Icon name={open ? 'chevron-up' : 'chevron-down'} size={20} color={colors.sage} />
      </Pressable>
      {open ? <View style={styles.body}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, minHeight: touch },
  pressed: { opacity: 0.7 },
  label: { flex: 1 },
  body: { gap: spacing.md },
});
