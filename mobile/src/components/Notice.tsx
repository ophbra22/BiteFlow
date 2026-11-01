import { Children, ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { useI18n } from '@/i18n/I18nProvider';
import { colors, radius, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, IconName } from './Icon';

type Tone = 'info' | 'success' | 'warning' | 'error';

type Props = {
  tone?: Tone;
  title?: string;
  message: string;
  icon?: IconName;
  /** Buttons shown under the message. */
  children?: ReactNode;
  /** Lay the buttons out side by side (wrapping when they do not fit). */
  row?: boolean;
};

const tones: Record<Tone, { color: string; icon: IconName; background: string }> = {
  info: { color: colors.muted, icon: 'info', background: colors.surface },
  success: { color: colors.sage, icon: 'check-circle', background: colors.sageTint },
  warning: { color: colors.butter, icon: 'alert-circle', background: colors.butterTint },
  error: { color: colors.danger, icon: 'alert-triangle', background: colors.dangerTint },
};

/** An inline message: offline, a failed save, a note about where data comes from. */
export function Notice({ tone = 'info', title, message, icon, children, row }: Props) {
  const { t } = useI18n();
  const look = tones[tone];
  // Conditional children that all evaluate to nothing count as no children.
  const hasChildren = Children.toArray(children).length > 0;
  return (
    <View
      style={[styles.box, { backgroundColor: look.background }]}
      accessible={!hasChildren}
      accessibilityRole={tone === 'error' ? 'alert' : undefined}
      accessibilityLiveRegion={tone === 'info' ? 'none' : 'polite'}
      accessibilityLabel={
        hasChildren
          ? undefined
          : `${tone === 'error' ? t('a11y.error') : t('a11y.notice')}. ${title ? `${title}. ` : ''}${message}`
      }>
      <View style={styles.row}>
        <View style={styles.icon}>
          <Icon name={icon ?? look.icon} color={look.color} size={20} />
        </View>
        <View style={styles.text}>
          {title ? (
            <AppText variant="bodyStrong" color={tone === 'info' ? colors.sand : look.color}>
              {title}
            </AppText>
          ) : null}
          <AppText variant="caption" color={tone === 'info' ? colors.muted : colors.sand}>
            {message}
          </AppText>
        </View>
      </View>
      {hasChildren ? <View style={row ? styles.rowActions : styles.actions}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.md },
  row: { flexDirection: 'row', gap: spacing.md },
  icon: { paddingTop: 2 },
  text: { flex: 1, gap: 2 },
  actions: { gap: spacing.sm },
  rowActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
