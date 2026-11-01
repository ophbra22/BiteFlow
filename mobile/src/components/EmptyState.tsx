import { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, IconName } from './Icon';

type Props = { icon: IconName; title: string; body?: string; children?: ReactNode };

/** What a blank area is for, and the action that fills it. */
export function EmptyState({ icon, title, body, children }: Props) {
  return (
    <View style={styles.wrap}>
      <View style={styles.icon}>
        <Icon name={icon} size={24} color={colors.sage} />
      </View>
      <View style={styles.text}>
        <AppText variant="section" center>
          {title}
        </AppText>
        {body ? (
          <AppText variant="caption" color={colors.muted} center>
            {body}
          </AppText>
        ) : null}
      </View>
      {children ? <View style={styles.actions}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', gap: spacing.md, paddingVertical: spacing.lg, paddingHorizontal: spacing.lg },
  icon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.sageTint,
  },
  text: { gap: spacing.xs },
  actions: { alignSelf: 'stretch', gap: spacing.sm },
});
