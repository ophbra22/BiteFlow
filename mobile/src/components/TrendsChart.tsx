import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Line, Rect, Text as SvgText } from 'react-native-svg';

import { displayValue, type DisplayUnit } from '@/domain/tracking';
import type { Metric, TrendPeriod } from '@/domain/trends';
import { useI18n } from '@/i18n/I18nProvider';
import { formatFullDay, formatNumber, localeTag } from '@/i18n/format';
import { parseIsoDay } from '@/domain/dates';
import { colors, fonts, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Button } from './Button';
import { Chip } from './Chip';

const GRID = [0, 0.5, 1];

/** Days over time. A chart keeps its left-to-right time axis in both languages. */
export function TrendsChart({
  period,
  metric,
  weightUnit = 'kg',
  waterUnit = 'ml',
}: {
  period: TrendPeriod;
  metric: Metric;
  weightUnit?: DisplayUnit;
  waterUnit?: DisplayUnit;
}) {
  const { t, language } = useI18n();
  const [primary, setPrimary] = useState(true);
  const [overlay, setOverlay] = useState(true);
  const [showData, setShowData] = useState(false);
  const unit = metric === 'weight' ? weightUnit : metric === 'water' ? waterUnit : metric === 'calories' ? 'kcal' : 'g';
  const convert = (n: number) => (metric === 'weight' || metric === 'water' ? displayValue(n, unit as DisplayUnit) : n);
  const targetKey = ({ calories: 'calorie_target', protein: 'protein_g', carbs: 'carbs_g', fat: 'fat_g', water: 'water_ml', weight: 'target_weight_kg' } as const)[metric];
  const max =
    Math.max(
      1,
      ...period.days.flatMap((d) => [
        d[metric] === null ? 0 : convert(d[metric]!),
        d.targets?.[targetKey] ? convert(d.targets[targetKey]!) : 0,
      ]),
    ) * 1.1;
  const weightMax = Math.max(1, ...period.days.map((d) => (d.weight === null ? 0 : displayValue(d.weight, weightUnit)))) * 1.1;
  const width = 400;
  const height = 230;
  const left = 44;
  const right = 356;
  const top = 18;
  const bottom = 190;
  const step = (right - left) / period.days.length;
  const y = (n: number, scale = max) => bottom - (n / scale) * (bottom - top);
  const x = (i: number) => left + step * (i + 0.5);
  const barRadius = Math.min(4, step * 0.2);
  const showOverlay = metric === 'calories' && overlay;
  // Digits only: a month name would break the left-to-right axis in Hebrew.
  const shortDate = (date: string) =>
    new Intl.DateTimeFormat(localeTag(language), { day: 'numeric', month: 'numeric' }).format(parseIsoDay(date));
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Chip testID="chart-primary" toggle selected={primary} label={t('tracking.primaryLayer')} onPress={() => setPrimary((v) => !v)} />
        {metric === 'calories' ? (
          <Chip testID="chart-weight" toggle selected={overlay} label={t('tracking.weightLayer')} onPress={() => setOverlay((v) => !v)} />
        ) : null}
      </View>
      <View style={styles.axes}>
        <AppText testID="chart-left-axis" variant="caption" color={colors.muted}>
          {metric === 'calories'
            ? t('tracking.calorieAxis')
            : `${t(metric === 'water' || metric === 'weight' ? `tracking.${metric}` : `nutrients.${metric}`)} · ${unit}`}
        </AppText>
        {showOverlay ? (
          <AppText testID="chart-right-axis" variant="caption" color={colors.rose}>
            {t('tracking.weightAxis', { unit: weightUnit })}
          </AppText>
        ) : null}
      </View>
      <View
        style={styles.plot}
        accessible
        accessibilityRole="image"
        accessibilityLabel={`${period.from} – ${period.to}. ${unit}${showOverlay ? `, ${weightUnit}` : ''}. ${t('tracking.sparse')}`}>
        <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
          {GRID.map((f) => (
            <Line key={`grid-${f}`} x1={left} x2={right} y1={y(f * max)} y2={y(f * max)} stroke={colors.line} strokeWidth={f === 0 ? 1.5 : 1} />
          ))}
          {GRID.map((f) => (
            <SvgText key={f} x={left - 6} y={y(f * max) + 4} fill={colors.muted} textAnchor="end" fontSize={11} fontFamily={fonts.regular}>
              {formatNumber(language, f * max, 0)}
            </SvgText>
          ))}
          {showOverlay
            ? GRID.map((f) => (
                <SvgText key={f} x={right + 6} y={y(f * weightMax, weightMax) + 4} fill={colors.rose} fontSize={11} fontFamily={fonts.regular}>
                  {formatNumber(language, f * weightMax, 0)}
                </SvgText>
              ))
            : null}
          {period.days.map((d, i) => {
            const v = d[metric];
            const target = d.targets?.[targetKey];
            return (
              <Bar
                key={d.date}
                date={d.date}
                barX={x(i) - step * 0.3}
                barWidth={step * 0.6}
                barRadius={barRadius}
                barTop={primary && v !== null ? y(convert(v)) : null}
                barBottom={bottom}
                targetFrom={x(i) - step * 0.45}
                targetTo={x(i) + step * 0.45}
                targetY={primary && target !== null && target !== undefined ? y(convert(target)) : null}
                weightX={x(i)}
                weightY={showOverlay && d.weight !== null ? y(displayValue(d.weight, weightUnit), weightMax) : null}
              />
            );
          })}
          <SvgText x={left} y={214} fill={colors.muted} fontSize={11} fontFamily={fonts.regular}>
            {shortDate(period.from)}
          </SvgText>
          <SvgText x={right} y={214} fill={colors.muted} textAnchor="end" fontSize={11} fontFamily={fonts.regular}>
            {shortDate(period.to)}
          </SvgText>
        </Svg>
      </View>
      <AppText variant="caption" color={colors.muted}>
        {t('tracking.goalLegend')}
      </AppText>
      <Button
        testID="chart-data-toggle"
        compact
        kind="ghost"
        label={language === 'he' ? (showData ? 'הסתרת ערכים יומיים' : 'הצגת ערכים יומיים') : showData ? 'Hide daily values' : 'Show daily values'}
        onPress={() => setShowData((v) => !v)}
      />
      {showData
        ? period.days.map((d) => {
            const values = [formatFullDay(language, d.date)];
            if (primary) {
              const name = t(metric === 'water' || metric === 'weight' ? `tracking.${metric}` : `nutrients.${metric}`);
              values.push(`${name}: ${d[metric] === null ? t('review.notProvided') : `${formatNumber(language, convert(d[metric]!), 1)} ${unit}`}`);
              if (d.partial[metric]) {
                values.push(
                  t('goals.statuses.partial'),
                  t('goals.known', { value: `${formatNumber(language, d.known_totals[metric], 1)} ${unit}` }),
                );
              }
              const target = d.targets?.[targetKey];
              values.push(
                target == null
                  ? t('goals.statuses.no_goal')
                  : t('tracking.target', { value: `${formatNumber(language, convert(target), 1)} ${unit}` }),
              );
              if (!d.logged && metric !== 'water' && metric !== 'weight') values.push(t('goals.statuses.unlogged'));
            }
            if (metric === 'calories' && overlay) {
              values.push(
                `${t('tracking.weight')}: ${d.weight === null ? t('review.notProvided') : `${formatNumber(language, displayValue(d.weight, weightUnit), 1)} ${weightUnit}`}`,
              );
            }
            const description = values.join('. ');
            return (
              <View key={d.date} testID={`chart-data-${d.date}`} accessible accessibilityLabel={description}>
                <AppText variant="caption">{description}</AppText>
              </View>
            );
          })
        : null}
    </View>
  );
}

type BarProps = {
  date: string;
  barX: number;
  barWidth: number;
  barRadius: number;
  barTop: number | null;
  barBottom: number;
  targetFrom: number;
  targetTo: number;
  targetY: number | null;
  weightX: number;
  weightY: number | null;
};

function Bar({ date, barX, barWidth, barRadius, barTop, barBottom, targetFrom, targetTo, targetY, weightX, weightY }: BarProps) {
  return (
    <>
      {barTop !== null ? (
        <Rect testID={`point-${date}`} x={barX} y={barTop} width={barWidth} height={barBottom - barTop} rx={barRadius} fill={colors.sage} />
      ) : null}
      {targetY !== null ? <Line x1={targetFrom} x2={targetTo} y1={targetY} y2={targetY} stroke={colors.butter} strokeWidth={2} strokeLinecap="round" /> : null}
      {weightY !== null ? <Circle testID={`weight-point-${date}`} cx={weightX} cy={weightY} r={4} fill={colors.rose} stroke={colors.surface} strokeWidth={1.5} /> : null}
    </>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  axes: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: spacing.sm },
  // A chart's time axis runs left to right in every language.
  plot: { direction: 'ltr' },
});
