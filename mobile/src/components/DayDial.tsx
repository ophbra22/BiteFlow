import { Pressable, StyleSheet, View } from 'react-native';
import Svg, { Circle, Line, Text as SvgText } from 'react-native-svg';

import type { Meal } from '@/api/types';
import { dialDots, dialPoint } from '@/domain/dial';
import type { GoalMetric } from '@/domain/goals';
import { useI18n } from '@/i18n/I18nProvider';
import { formatNumber } from '@/i18n/format';
import { haptics } from '@/native/haptics';
import { colors, fonts, mealColors, radius, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon } from './Icon';

const SIZE = 300;
const CENTRE = SIZE / 2;
const RING = 124;
const PROGRESS = 94;
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const LABELS = [0, 6, 12, 18];

type Props = {
  meals: Meal[];
  onAdd: () => void;
  onOpenMeal: (meal: Meal) => void;
  addDisabled?: boolean;
  caloriesGoal?: GoalMetric;
  /** The day's headline, already formatted; "–" while loading or when a value is missing. */
  calories?: string;
  /** One short line under the headline: the goal, or what the number means. */
  caption?: string;
};

/**
 * The day as a 24-hour ring: a dot per meal, progress towards the calorie goal,
 * and the day's total with the add button at the centre.
 * A clock is never mirrored, so the ring looks the same in Hebrew and English.
 */
export function DayDial({ meals, onAdd, onOpenMeal, addDisabled, caloriesGoal, calories, caption }: Props) {
  const { t, language } = useI18n();
  const dots = dialDots(meals);
  const byId = new Map(meals.map((meal) => [meal.id, meal]));
  const showProgress = caloriesGoal?.percent != null && caloriesGoal.status !== 'unlogged';
  const circumference = 2 * Math.PI * PROGRESS;
  return (
    <View style={styles.wrap}>
      <Svg
        style={StyleSheet.absoluteFill}
        width="100%"
        height="100%"
        viewBox={`-14 -14 ${SIZE + 28} ${SIZE + 28}`}
        accessible
        accessibilityRole="image"
        accessibilityLabel={`${t('a11y.dial')}${caloriesGoal?.percent != null ? `. ${t('nutrients.calories')}: ${formatNumber(language, caloriesGoal.percent, 1)}%. ${t('goals.loggedOnly')}` : ''}`}>
        <Circle cx={CENTRE} cy={CENTRE} r={RING} stroke={colors.surface} strokeWidth={26} fill="none" />
        <Circle cx={CENTRE} cy={CENTRE} r={PROGRESS} stroke={colors.surface} strokeWidth={8} fill="none" />
        {showProgress ? (
          <Circle
            testID="dial-goal-progress"
            cx={CENTRE}
            cy={CENTRE}
            r={PROGRESS}
            fill="none"
            stroke={colors.sage}
            strokeWidth={8}
            strokeLinecap="round"
            strokeDasharray={`${circumference} ${circumference}`}
            strokeDashoffset={circumference * (1 - Math.min(100, Math.max(0, caloriesGoal.percent!)) / 100)}
            rotation={-90}
            origin={`${CENTRE}, ${CENTRE}`}
            accessible
            accessibilityLabel={`${t('nutrients.calories')}: ${formatNumber(language, caloriesGoal.percent!, 1)}%. ${t(`goals.statuses.${caloriesGoal.status}`)}. ${t('goals.loggedOnly')}`}
          />
        ) : null}
        {HOURS.map((hour) => {
          const major = hour % 6 === 0;
          const from = dialPoint(hour * 60, RING - 13, CENTRE);
          const to = dialPoint(hour * 60, RING - (major ? 3 : 9), CENTRE);
          return (
            <Line
              key={hour}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={colors.muted}
              strokeOpacity={major ? 0.9 : 0.35}
              strokeWidth={1.5}
              strokeLinecap="round"
            />
          );
        })}
        {LABELS.map((hour) => {
          const point = dialPoint(hour * 60, RING + 22, CENTRE);
          return (
            <SvgText
              key={hour}
              x={point.x}
              y={point.y + 4}
              fill={colors.muted}
              fontSize={12}
              fontFamily={fonts.regular}
              textAnchor="middle">
              {String(hour).padStart(2, '0')}
            </SvgText>
          );
        })}
        {dots.map((dot) => {
          const point = dialPoint(dot.minutes, RING, CENTRE);
          const meal = byId.get(dot.id);
          const open = meal ? () => onOpenMeal(meal) : undefined;
          return (
            <Circle
              key={dot.id}
              testID={`dial-meal-${dot.id}`}
              cx={point.x}
              cy={point.y}
              r={dot.radius}
              fill={mealColors[dot.mealType]}
              stroke={colors.ground}
              strokeWidth={3}
              onPress={open}
            />
          );
        })}
      </Svg>
      <View style={styles.core} pointerEvents="box-none">
        {calories ? (
          <View style={styles.total} accessible accessibilityLabel={[calories, t('units.kcal'), caption].filter(Boolean).join(', ')}>
            <AppText testID="dial-calories" variant="figure" center maxFontSizeMultiplier={1.15} numberOfLines={1} adjustsFontSizeToFit>
              {calories}
            </AppText>
            <AppText variant="caption" color={colors.muted} center maxFontSizeMultiplier={1.15} numberOfLines={2}>
              {caption ?? t('units.kcal')}
            </AppText>
          </View>
        ) : null}
        <Pressable
          testID="add-meal"
          accessibilityRole="button"
          accessibilityLabel={t('home.addMeal')}
          accessibilityState={{ disabled: !!addDisabled }}
          disabled={addDisabled}
          onPress={() => {
            haptics.tap();
            onAdd();
          }}
          style={({ pressed }) => [styles.add, pressed && styles.pressed, addDisabled && styles.disabled]}>
          <Icon name="plus" size={18} color={colors.onSage} />
          <AppText variant="label" color={colors.onSage} center numberOfLines={1} maxFontSizeMultiplier={1.15}>
            {t('home.addMeal')}
          </AppText>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  // The dial keeps its left-to-right geometry even when the app layout is mirrored.
  wrap: {
    width: '100%',
    maxWidth: 340,
    aspectRatio: 1,
    alignSelf: 'center',
    alignItems: 'center',
    justifyContent: 'center',
    direction: 'ltr',
  },
  core: { width: '50%', alignItems: 'center', gap: spacing.sm },
  total: { alignSelf: 'stretch', alignItems: 'center' },
  add: {
    minHeight: touch,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    borderRadius: radius.pill,
    backgroundColor: colors.sage,
    paddingHorizontal: spacing.md,
  },
  pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },
  disabled: { opacity: 0.5 },
});
