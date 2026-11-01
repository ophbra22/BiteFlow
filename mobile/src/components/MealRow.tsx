import { Pressable, StyleSheet, View } from 'react-native';

import type { Meal } from '@/api/types';
import { consumedAt } from '@/domain/dial';
import { useI18n } from '@/i18n/I18nProvider';
import { formatNumber, formatQuantity, formatTime } from '@/i18n/format';
import { foodName } from '@/i18n/translate';
import { colors, macroColors, mealColors, radius, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon, directional } from './Icon';

type Props = { meal: Meal; onPress: () => void; divider?: boolean };

/** Name of a saved meal: catalog foods are translated, products and manual entries are shown as saved. */
export function useMealName() {
  const { language } = useI18n();
  return (meal: Pick<Meal, 'food_id' | 'name'>) => foodName(language, meal.food_id, meal.name);
}

const MACROS = ['protein', 'carbs', 'fat'] as const;

/** One saved item: what it was, how much and when, with its energy and macros at a glance. */
export function MealRow({ meal, onPress, divider }: Props) {
  const { t, language } = useI18n();
  const name = useMealName()(meal);
  const amount = formatQuantity(language, meal.grams, meal.details.basis_unit ?? 'g');
  // The clock time is shown only when the meal was logged on the day it belongs to.
  const time = consumedAt(meal) ? formatTime(language, consumedAt(meal)!, meal.details.timezone_id ?? undefined) : null;
  const kcal = formatNumber(language, meal.calories);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${t('a11y.mealRow', { name, amount, kcal })}. ${t(`mealTypes.${meal.meal_type}`)}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, divider && styles.divider, pressed && styles.pressed]}>
      <View style={[styles.tile, { borderColor: mealColors[meal.meal_type] }]}>
        <AppText style={styles.emoji} maxFontSizeMultiplier={1.2}>
          {meal.emoji}
        </AppText>
      </View>
      <View style={styles.text}>
        <AppText variant="bodyStrong">{name}</AppText>
        <View style={styles.meta}>
          <AppText variant="caption" color={colors.muted}>
            {amount}
          </AppText>
          {time ? (
            <AppText variant="caption" color={colors.muted}>
              {time}
            </AppText>
          ) : null}
        </View>
        <View style={styles.meta} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
          {MACROS.map((key) =>
            meal[key] === null ? null : (
              <View key={key} style={styles.macro}>
                <View style={[styles.macroDot, { backgroundColor: macroColors[key] }]} />
                <AppText variant="caption" color={colors.muted}>
                  {formatQuantity(language, meal[key], 'g', 0)}
                </AppText>
              </View>
            ),
          )}
        </View>
      </View>
      <View style={styles.energy}>
        <AppText variant={meal.calories === null ? 'caption' : 'number'} color={meal.calories === null ? colors.muted : colors.sand}>
          {kcal}
        </AppText>
        {meal.calories === null ? null : (
          <AppText variant="caption" color={colors.muted}>
            {t('units.kcal')}
          </AppText>
        )}
      </View>
      <Icon name={directional.forward} size={18} color={colors.muted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    minHeight: 72,
  },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  pressed: { backgroundColor: colors.field },
  // The ring carries the meal colour; the emoji comes from the saved food.
  tile: {
    width: 44,
    height: 44,
    borderRadius: radius.sm,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emoji: { fontSize: 22, lineHeight: 28 },
  text: { flex: 1, gap: 2 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', columnGap: spacing.sm },
  macro: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  macroDot: { width: 6, height: 6, borderRadius: 3 },
  energy: { alignItems: 'flex-end' },
});
