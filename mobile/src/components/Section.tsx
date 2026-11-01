import { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { spacing } from '@/theme/tokens';

import { AppText } from './AppText';

type Props = { title: string; trailing?: ReactNode; children: ReactNode };

/** A titled group on a screen; the title is a header for screen readers. */
export function Section({ title, trailing, children }: Props) {
  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <AppText variant="section" accessibilityRole="header" style={styles.title}>
          {title}
        </AppText>
        {trailing}
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { gap: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, minHeight: 32 },
  title: { flex: 1 },
});
