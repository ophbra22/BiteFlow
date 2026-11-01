import { StyleSheet, View } from 'react-native';

import type { DaySummary } from '@/api/types';
import type { GoalProgress } from '@/domain/goals';
import { macroEnergyShare } from '@/domain/nutrition';
import { useI18n } from '@/i18n/I18nProvider';
import { formatQuantity } from '@/i18n/format';
import { colors, macroColors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Meter } from './Meter';

const MACROS = ['protein', 'carbs', 'fat'] as const;

type Props = { summary: DaySummary | null; progress?: GoalProgress | null };

/** Protein, carbohydrates and fat side by side: against the goal when one is set, otherwise as a share of energy. */
export function MacroSummary({ summary, progress }: Props) {
  const { t, language } = useI18n();
  const share = summary ? macroEnergyShare(summary) : null;
  return (
    <View style={styles.row}>
      {MACROS.map((key) => {
        const metric = progress?.[key];
        const value = summary?.[key] ?? null;
        const hasTarget = metric?.target != null;
        const percent =
          metric?.percent != null && metric.status !== 'unlogged'
            ? metric.percent
            : !hasTarget && share
              ? share[key] * 100
              : 0;
        const name = key === 'carbs' ? t('nutrients.carbsShort') : t(`nutrients.${key}`);
        const amount = summary ? formatQuantity(language, value, 'g', 0) : '–';
        const target = hasTarget ? formatQuantity(language, metric.target, 'g', 0) : null;
        return (
          <View
            key={key}
            style={styles.item}
            accessible
            accessibilityLabel={`${t(`nutrients.${key}`)}: ${amount}${target ? ` / ${target}` : ''}`}>
            <AppText variant="caption" color={colors.muted} numberOfLines={1}>
              {name}
            </AppText>
            <AppText variant={value === null && summary ? 'caption' : 'number'}>{amount}</AppText>
            <Meter percent={percent} color={macroColors[key]} height={6} />
            {target ? (
              <AppText variant="caption" color={colors.muted} numberOfLines={1}>
                {target}
              </AppText>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: spacing.lg },
  item: { flex: 1, gap: spacing.xs },
});
