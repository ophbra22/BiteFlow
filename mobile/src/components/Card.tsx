import { ReactNode } from 'react';
import { StyleProp, StyleSheet, View, ViewProps, ViewStyle } from 'react-native';

import { colors, radius, spacing } from '@/theme/tokens';

type Props = ViewProps & {
  children: ReactNode;
  /** Rows supply their own padding, so the dividers reach the card's edges. */
  flush?: boolean;
  style?: StyleProp<ViewStyle>;
};

/** One raised area on the pine ground. Cards are never nested. */
export function Card({ children, flush, style, ...rest }: Props) {
  return (
    <View {...rest} style={[styles.card, flush ? styles.flush : styles.padded, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.lg },
  padded: { padding: spacing.lg, gap: spacing.md },
  flush: { overflow: 'hidden' },
});
