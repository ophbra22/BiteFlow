import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { Disclosure } from '@/components/Disclosure';
import { Header } from '@/components/Header';
import { directional } from '@/components/Icon';
import { IconButton } from '@/components/IconButton';
import { ListRow } from '@/components/ListRow';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { Segmented } from '@/components/Segmented';
import { Skeleton } from '@/components/Skeleton';
import { TrendsChart } from '@/components/TrendsChart';
import { useTrends } from '@/data/useTracking';
import { addDays, isIsoDay, parseIsoDay, todayIso, toIsoDay } from '@/domain/dates';
import { displayValue, type DisplayUnit } from '@/domain/tracking';
import { METRICS, periodDates, type Metric } from '@/domain/trends';
import { useI18n } from '@/i18n/I18nProvider';
import { formatDay, formatNumber } from '@/i18n/format';
import { colors, spacing } from '@/theme/tokens';

export default function Trends() {
  const { day } = useLocalSearchParams<{ day?: string }>();
  const { t, language } = useI18n();
  const [anchor, setAnchor] = useState(isIsoDay(day) ? day : todayIso());
  const [mode, setMode] = useState<'week' | 'month'>('week');
  const [metric, setMetric] = useState<Metric>('calories');
  const [weightUnit, setWeightUnit] = useState<DisplayUnit>('kg');
  const [waterUnit, setWaterUnit] = useState<DisplayUnit>('ml');
  const { from, to } = periodDates(anchor, mode);
  const state = useTrends(from, to);
  const data = state.data;
  const unit = metric === 'weight' ? weightUnit : metric === 'water' ? waterUnit : metric === 'calories' ? 'kcal' : 'g';
  const formatted = (n: number | null) =>
    n === null
      ? t('tracking.unknown')
      : `${n < 0 ? '−' : ''}${formatNumber(language, metric === 'weight' || metric === 'water' ? displayValue(Math.abs(n), unit as DisplayUnit) : Math.abs(n), 1)} ${unit}`;
  const move = (direction: number) => {
    if (mode === 'week') setAnchor(addDays(from, direction * 7));
    else {
      const d = parseIsoDay(from);
      setAnchor(toIsoDay(new Date(d.getFullYear(), d.getMonth() + direction, 1, 12)));
    }
  };
  const averageCount =
    metric === 'weight'
      ? data?.current.statistics.measured_days
      : metric === 'water'
        ? data?.current.statistics.water_logged_days
        : data?.current.statistics.logged_days;
  return (
    <Screen header={<Header title={t('tracking.trends')} />}>
      <Segmented
        label={t('tracking.period')}
        value={mode}
        onChange={setMode}
        options={(['week', 'month'] as const).map((m) => ({ value: m, label: t(`tracking.${m}`) }))}
      />
      <View style={styles.range}>
        <IconButton icon={directional.back} label={t('tracking.previous')} onPress={() => move(-1)} />
        <AppText variant="label" center style={styles.flex}>
          {formatDay(language, from)} – {formatDay(language, to)}
        </AppText>
        <IconButton icon={directional.forward} label={t('tracking.next')} onPress={() => move(1)} />
      </View>
      <View style={styles.chips} accessibilityRole="radiogroup">
        {METRICS.map((m) => (
          <Chip
            key={m}
            radio
            selected={m === metric}
            label={t(m === 'water' || m === 'weight' ? `tracking.${m}` : `nutrients.${m}`)}
            onPress={() => setMetric(m)}
          />
        ))}
      </View>

      {state.enabled === false ? <Notice message={t('tracking.noTrends')} /> : null}
      {state.error ? (
        <Notice tone="error" message={t(errorMessageKey(state.error))}>
          <Button
            compact
            kind="secondary"
            label={t('common.retry')}
            onPress={() => {
              void state.refresh();
            }}
          />
        </Notice>
      ) : null}
      {!state.fresh && data ? (
        <Notice tone="warning" message={t('tracking.stale')}>
          <Button
            compact
            kind="ghost"
            label={t('common.retry')}
            onPress={() => {
              void state.refresh();
            }}
          />
        </Notice>
      ) : null}
      {!data && state.enabled !== false && !state.error ? (
        <Card accessibilityLabel={t('common.loading')}>
          <Skeleton height={40} width="50%" />
          <Skeleton height={180} />
        </Card>
      ) : null}

      {data ? (
        <>
          {data.current.statistics.insufficient_data ? <Notice tone="warning" message={t('tracking.sparse')} /> : null}
          <Card>
            <View style={styles.stats}>
              <View style={styles.stat}>
                <AppText variant="caption" color={colors.muted}>
                  {t(metric === 'weight' ? 'tracking.weightAverage' : metric === 'water' ? 'tracking.waterAverage' : 'tracking.averages')}
                </AppText>
                <AppText variant="heading">{formatted(data.current.statistics.average[metric])}</AppText>
                <AppText variant="caption" color={colors.muted}>
                  ({averageCount})
                </AppText>
              </View>
              <View style={styles.stat}>
                <AppText variant="caption" color={colors.muted}>
                  {t('tracking.compare', { from: formatDay(language, data.previous.from), to: formatDay(language, data.previous.to) })}
                </AppText>
                <AppText variant="heading">{t('tracking.difference', { value: formatted(data.comparison[metric]) })}</AppText>
              </View>
            </View>
            <AppText variant="caption" color={colors.muted}>
              {t('tracking.denominator', { count: data.current.statistics.logged_days, missing: data.current.statistics.unlogged_days })}
            </AppText>
            <AppText variant="caption" color={colors.muted}>
              {t('tracking.adherence', {
                met: data.current.statistics.calorie_in_range,
                logged: data.current.statistics.logged_days,
                eligible: data.current.statistics.calorie_eligible_days,
              })}
            </AppText>
          </Card>
          <Card>
            <TrendsChart period={data.current} metric={metric} weightUnit={weightUnit} waterUnit={waterUnit} />
          </Card>
          <View style={styles.chips}>
            <Chip label={t('tracking.units', { unit: weightUnit })} onPress={() => setWeightUnit(weightUnit === 'kg' ? 'lb' : 'kg')} />
            <Chip label={t('tracking.units', { unit: waterUnit })} onPress={() => setWaterUnit(waterUnit === 'ml' ? 'fl oz' : 'ml')} />
          </View>
          <Notice message={t('tracking.recorded')} />
          <Disclosure label={t('tracking.dailyBreakdown')}>
            <Card flush>
              {data.current.days.map((d, index) => {
                const nutrition = metric === 'calories' || metric === 'protein' || metric === 'carbs' || metric === 'fat';
                const source = nutrition
                  ? t('tracking.sourceStatus', {
                      value:
                        d.nutrition_sources
                          .map((s) => t(`tracking.statusLabels.${s as 'verified' | 'user_confirmed' | 'estimated' | 'legacy_unknown'}`))
                          .join(', ') || t('tracking.unknown'),
                    })
                  : (metric === 'weight' ? [d.weight_source] : d.water_sources)
                      .filter(Boolean)
                      .map((s) => t(`tracking.sources.${s as 'manual' | 'apple_health' | 'health_connect'}`))
                      .join(', ') || t('tracking.unknown');
                return (
                  <ListRow
                    key={d.date}
                    divider={index > 0}
                    title={formatDay(language, d.date)}
                    hint={nutrition && d.estimated ? `${source}. ${t('tracking.estimated')}` : source}
                    value={formatted(d[metric])}
                    accessibilityHint={t('tracking.dayDetails', { day: formatDay(language, d.date) })}
                    onPress={() => router.push({ pathname: '/', params: { day: d.date } })}
                  />
                );
              })}
            </Card>
          </Disclosure>
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  range: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg },
  stat: { flexGrow: 1, flexBasis: '45%', gap: 2 },
});
