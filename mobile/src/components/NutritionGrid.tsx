import { StyleSheet, View } from 'react-native';

import { BasisUnit, CORE_NUTRIENTS, Nutrient, OPTIONAL_NUTRIENTS } from '@/domain/nutrition';
import { useI18n } from '@/i18n/I18nProvider';
import { formatNumber } from '@/i18n/format';
import { colors, macroColors, radius, spacing } from '@/theme/tokens';

import { AppText } from './AppText';

type Values = Partial<Record<Nutrient, number | null | undefined>>;

type Props = {
  values: Values;
  testID?: string;
  /** Also list sugars, saturated fat, fibre, salt and sodium. */
  showOptional?: boolean;
  /** Shown instead of numbers, for example before an amount is entered. */
  placeholder?: boolean;
  basisUnit?: BasisUnit;
};

const ACCENT: Partial<Record<Nutrient, string>> = {
  calories: colors.sand,
  ...macroColors,
};

/**
 * Energy and macros as four figures, optional label values as rows.
 * A missing value is written out as "Not provided"; it is never shown as 0.
 */
export function NutritionGrid({ values, showOptional, placeholder, testID }: Props) {
  const { t, language } = useI18n();
  const unit = (key: Nutrient) => (key === 'calories' ? t('units.kcal') : t('units.g'));
  const text = (key: Nutrient) => {
    const value = values[key];
    if (placeholder) return '–';
    return value == null ? t('review.notProvided') : formatNumber(language, value, 1);
  };
  const optional = OPTIONAL_NUTRIENTS.filter(() => showOptional);
  return (
    <View style={styles.wrap}>
      <View style={styles.tiles}>
        {CORE_NUTRIENTS.map((key) => {
          const known = !placeholder && values[key] != null;
          return (
            <View
              key={key}
              style={styles.tile}
              accessible
              accessibilityLabel={`${t(`nutrients.${key}`)}: ${text(key)}${known ? ` ${unit(key)}` : ''}`}>
              <View style={[styles.accent, { backgroundColor: ACCENT[key] }]} />
              <AppText testID={testID ? `${testID}-${key}` : undefined} variant={known ? 'number' : 'caption'} center>
                {text(key)}
              </AppText>
              <AppText variant="caption" color={colors.muted} center numberOfLines={1}>
                {known ? unit(key) : ''}
              </AppText>
              <AppText variant="caption" color={colors.muted} center numberOfLines={1}>
                {key === 'carbs' ? t('nutrients.carbsShort') : t(`nutrients.${key}`)}
              </AppText>
            </View>
          );
        })}
      </View>
      {optional.map((key) => (
        <View
          key={key}
          style={styles.line}
          accessible
          accessibilityLabel={`${t(`nutrients.${key}`)}: ${text(key)}${values[key] != null ? ` ${unit(key)}` : ''}`}>
          <AppText variant="caption" color={colors.muted} style={styles.lineLabel}>
            {t(`nutrients.${key}`)}
          </AppText>
          <AppText variant="label" color={values[key] == null ? colors.muted : colors.sand}>
            {values[key] == null || placeholder ? text(key) : `${text(key)} ${unit(key)}`}
          </AppText>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tile: {
    flexGrow: 1,
    flexBasis: '22%',
    minWidth: 68,
    alignItems: 'center',
    backgroundColor: colors.field,
    borderRadius: radius.sm,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.xs,
    gap: 1,
  },
  accent: { width: 16, height: 3, borderRadius: 2, marginBottom: spacing.xs },
  line: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.xs,
    minHeight: 30,
  },
  lineLabel: { flex: 1 },
});
