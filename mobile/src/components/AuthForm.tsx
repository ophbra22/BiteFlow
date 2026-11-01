import { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { useI18n } from '@/i18n/I18nProvider';
import { colors, radius, spacing } from '@/theme/tokens';

import { AppText } from './AppText';

/** The brand mark: a meal orbiting the day. Its own geometry is never mirrored. */
function OrbitMark() {
  return (
    <View style={styles.mark} accessibilityElementsHidden importantForAccessibility="no">
      <View style={styles.ring}>
        <View style={styles.core} />
        <View style={[styles.dot, styles.dotA]} />
        <View style={[styles.dot, styles.dotB]} />
        <View style={[styles.dot, styles.dotC]} />
      </View>
    </View>
  );
}

/** Shared top of the sign-in, register and recovery screens. */
export function AuthIntro({ title, body }: { title: string; body?: string }) {
  const { t } = useI18n();
  return (
    <View style={styles.intro}>
      <View style={styles.brand}>
        <OrbitMark />
        <AppText variant="heading">{t('common.appName')}</AppText>
      </View>
      <AppText variant="title" accessibilityRole="header">
        {title}
      </AppText>
      {body ? (
        <AppText variant="body" color={colors.muted}>
          {body}
        </AppText>
      ) : null}
    </View>
  );
}

/** "Or" between two ways of doing the same thing. */
export function AuthDivider({ label }: { label: string }) {
  return (
    <View style={styles.divider}>
      <View style={styles.rule} />
      <AppText variant="caption" color={colors.muted} center style={styles.dividerLabel}>
        {label}
      </AppText>
      <View style={styles.rule} />
    </View>
  );
}

export function FormStack({ children }: { children: ReactNode }) {
  return <View style={styles.form}>{children}</View>;
}

const styles = StyleSheet.create({
  intro: { gap: spacing.sm, paddingTop: spacing.xl },
  brand: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, marginBottom: spacing.xl },
  mark: { direction: 'ltr', padding: spacing.xs },
  ring: {
    width: 48,
    height: 48,
    borderRadius: 24,
    borderWidth: 6,
    borderColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  core: { width: 18, height: 18, borderRadius: 9, backgroundColor: colors.sage },
  dot: { position: 'absolute', width: 11, height: 11, borderRadius: radius.pill, borderWidth: 2, borderColor: colors.ground },
  dotA: { backgroundColor: colors.butter, top: 2, right: -8 },
  dotB: { backgroundColor: colors.rose, bottom: -8, left: 12 },
  dotC: { backgroundColor: colors.lilac, top: 8, left: -9 },
  divider: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  rule: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: colors.line },
  dividerLabel: { flexShrink: 1 },
  form: { gap: spacing.lg },
});
