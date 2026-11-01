import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import type { Meal } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Chip } from '@/components/Chip';
import { DayDial } from '@/components/DayDial';
import { DayNav } from '@/components/DayNav';
import { Disclosure } from '@/components/Disclosure';
import { DraftPersistenceNotice } from '@/components/DraftPersistenceNotice';
import { EmptyState } from '@/components/EmptyState';
import { GoalDashboard } from '@/components/GoalDashboard';
import { Icon, IconName } from '@/components/Icon';
import { IconButton } from '@/components/IconButton';
import { MacroSummary } from '@/components/MacroSummary';
import { MealRow } from '@/components/MealRow';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { Section } from '@/components/Section';
import { Skeleton } from '@/components/Skeleton';
import { WaterToday } from '@/components/WaterToday';
import { useDraft } from '@/data/DraftProvider';
import { setAddIntent } from '@/data/add-intent';
import { useDay } from '@/data/useDay';
import { useGoals } from '@/data/useGoals';
import { useTracking } from '@/data/useTracking';
import { addDays, isIsoDay, todayIso } from '@/domain/dates';
import { resumeDraftPath } from '@/domain/drafts';
import { effectiveGoal, goalProgress } from '@/domain/goals';
import { MEAL_TYPES, macroEnergyShare } from '@/domain/nutrition';
import { useOnline } from '@/hooks/useOnline';
import { useI18n } from '@/i18n/I18nProvider';
import { adviceText } from '@/i18n/advice';
import { formatNumber, formatQuantity, formatTime } from '@/i18n/format';
import { habitsText } from '@/i18n/habits';
import { foodName } from '@/i18n/translate';
import { captureAccountStorage } from '@/storage/kv';
import { sharePrivateExport } from '@/storage/export';
import { colors, mealColors, radius, spacing, touch } from '@/theme/tokens';

export default function Home() {
  const { day: requestedDay } = useLocalSearchParams<{ day?: string }>();
  return <HomeDay key={requestedDay ?? 'current'} initialDay={isIsoDay(requestedDay) ? requestedDay : todayIso()} />;
}

function HomeDay({ initialDay }: { initialDay: string }) {
  const { t, language } = useI18n();
  const { api, user } = useAuth();
  const online = useOnline();
  const { draft, discard } = useDraft();
  const [day, setDay] = useState(initialDay);
  const { data, loading, fresh, savedAt, error, refresh } = useDay(day);
  const [pulling, setPulling] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const tracking = useTracking('water', day);
  const isToday = day === todayIso();
  const meals = data?.meals ?? [];
  const summary = data?.summary ?? null;
  const goals = useGoals();
  const goal = effectiveGoal(goals.data, day);
  const progress = goals.enabled && summary ? goalProgress(summary, goal) : null;
  const share = summary ? macroEnergyShare(summary) : null;

  const startAdd = () => {
    setAddIntent({ day });
    router.push('/add');
  };
  const openMeal = (meal: Meal) => router.push({ pathname: '/meal/[id]', params: { id: meal.id, day: meal.day } });

  const exportDay = async () => {
    setExportError(null);
    if (!meals.length) {
      setExportError(t('journal.exportEmpty'));
      return;
    }
    setExporting(true);
    try {
      if (!user) return;
      const ownerCheck = captureAccountStorage(user.id);
      const sessionCheck = api.captureSession();
      await sharePrivateExport({
        name: `biteflow-${day}.csv`,
        mime: 'text/csv',
        load: () => api.exportCsv(day),
        check: () => {
          ownerCheck();
          sessionCheck();
        },
      });
    } catch (failure) {
      const key = errorMessageKey(failure);
      setExportError(key === 'errors.unknown' ? t('journal.exportFailed') : t(key));
    } finally {
      setExporting(false);
    }
  };

  const savedTime = savedAt ? formatTime(language, savedAt) : '';
  const draftName = draft
    ? draft.foodId
      ? foodName(language, draft.foodId, draft.name)
      : draft.name.trim() || t('add.untitled')
    : '';

  const calorieMetric = progress?.calories;
  const dialCaption =
    calorieMetric?.target != null
      ? calorieMetric.remaining !== null && calorieMetric.status !== 'unlogged'
        ? t(calorieMetric.remaining < 0 ? 'goals.over' : 'goals.remaining', {
            value: formatQuantity(language, Math.abs(calorieMetric.remaining), 'kcal', 0),
          })
        : `/ ${formatQuantity(language, calorieMetric.target, 'kcal', 0)}`
      : summary && summary.calories === null
        ? t('goals.statuses.partial')
        : t('units.kcal');

  const groups = MEAL_TYPES.map((type) => ({ type, items: meals.filter((meal) => meal.meal_type === type) })).filter(
    (group) => group.items.length > 0,
  );

  const tools: { key: string; icon: IconName; label: string; onPress: () => void }[] = [
    { key: 'trends', icon: 'bar-chart-2', label: t('tracking.trends'), onPress: () => router.push({ pathname: '/trends', params: { day } }) },
    { key: 'weight', icon: 'activity', label: t('tracking.weight'), onPress: () => router.push({ pathname: '/weight', params: { day } }) },
    { key: 'insights', icon: 'trending-up', label: adviceText(language, 'insight'), onPress: () => router.push({ pathname: '/insights', params: { day } }) },
    { key: 'recommendations', icon: 'compass', label: adviceText(language, 'recommendation'), onPress: () => router.push({ pathname: '/recommendations', params: { day } }) },
    { key: 'reminders', icon: 'bell', label: habitsText(language, 'title'), onPress: () => router.push('/reminders') },
  ];

  const copyFromYesterday = () =>
    router.push({ pathname: '/copy', params: { source: addDays(day, -1), destination: day } });
  const copyToTomorrow = () => router.push({ pathname: '/copy', params: { source: day, destination: addDays(day, 1) } });

  return (
    <Screen
      header={
        <View style={styles.header}>
          <DayNav day={day} onChange={setDay} />
          <View style={styles.actions}>
            {exporting ? (
              <View style={styles.spinner} accessibilityLabel={t('journal.exporting')}>
                <ActivityIndicator color={colors.sand} />
              </View>
            ) : (
              <IconButton testID="export" icon="share" label={t('journal.export')} onPress={exportDay} />
            )}
            <IconButton testID="settings" icon="sliders" label={t('home.openSettings')} onPress={() => router.push('/settings')} />
          </View>
        </View>
      }
      refreshControl={
        <RefreshControl
          key={day}
          refreshing={pulling}
          tintColor={colors.sand}
          colors={[colors.ground]}
          progressBackgroundColor={colors.sage}
          onRefresh={async () => {
            setPulling(true);
            try {
              await refresh();
            } finally {
              setPulling(false);
            }
          }}
        />
      }>
      <DraftPersistenceNotice />
      {!online ? <Notice tone="warning" icon="wifi-off" message={t('states.offline')} /> : null}

      {draft ? (
        <Notice row tone="warning" icon="edit-3" title={t('add.resumeTitle')} message={t('add.resumeBody', { name: draftName })}>
          <Button compact testID="resume-draft" label={t('add.resume')} onPress={() => router.push(resumeDraftPath(draft))} />
          <Button compact kind="ghost" label={t('add.discard')} onPress={discard} />
        </Notice>
      ) : null}

      {!isToday ? (
        <View style={styles.today}>
          <Chip icon="corner-up-left" label={t('dates.backToToday')} onPress={() => setDay(todayIso())} />
        </View>
      ) : null}

      {data && !fresh && !loading ? (
        <Notice tone="warning" icon="cloud-off" message={t(online ? 'states.staleSaved' : 'states.offlineSaved', { time: savedTime })}>
          <Button compact kind="secondary" label={t('common.retry')} onPress={refresh} />
        </Notice>
      ) : null}

      {!data && !loading && error ? (
        <Notice
          tone="error"
          title={t('states.loadFailedTitle')}
          message={error.outcomeUnknown && !online ? t('states.offlineNoData') : t(errorMessageKey(error))}>
          <Button kind="secondary" label={t('common.retry')} onPress={refresh} />
        </Notice>
      ) : null}

      <DayDial
        meals={meals}
        onAdd={startAdd}
        onOpenMeal={openMeal}
        caloriesGoal={progress?.calories}
        calories={summary && summary.calories !== null ? formatNumber(language, summary.calories) : '–'}
        caption={dialCaption}
      />

      <Card
        accessible={!!summary}
        accessibilityLabel={
          summary
            ? `${t('a11y.dailyTotals')}: ${formatQuantity(language, summary.calories, 'kcal', 0)}. ${t('home.items', { count: summary.count })}. ${share ? t('home.macroSplit', { protein: Math.round(share.protein * 100), carbs: Math.round(share.carbs * 100), fat: Math.round(share.fat * 100) }) : ''}`
            : t('a11y.dailyTotals')
        }>
        <AppText variant="caption" color={colors.muted}>
          {isToday ? t('home.soFarToday') : t('home.loggedOnDay')}
          {summary ? `, ${t('home.items', { count: summary.count })}` : ''}
        </AppText>
        <MacroSummary summary={summary} progress={progress} />
      </Card>

      {goals.enabled && goals.saving ? <Notice message={t('goals.pending')} /> : null}
      {goals.enabled && !goals.fresh && !goals.loading ? <Notice tone="warning" message={t('goals.stale')} /> : null}
      {exportError ? <Notice tone="warning" message={exportError} /> : null}

      <Section title={t('home.mealsTitle')}>
        {!data && loading ? (
          <Card accessibilityLabel={t('common.loading')}>
            <Skeleton height={44} />
            <Skeleton height={44} />
          </Card>
        ) : null}

        {data && meals.length === 0 ? (
          <Card flush>
            <EmptyState icon="coffee" title={t('home.emptyTitle')} body={t('home.emptyBody')}>
              <Button compact kind="secondary" icon="copy" label={t('copy.yesterday')} onPress={copyFromYesterday} />
            </EmptyState>
          </Card>
        ) : null}

        {groups.map((group) => (
          <View key={group.type} style={styles.group}>
            <View style={styles.groupHead}>
              <View style={[styles.groupDot, { backgroundColor: mealColors[group.type] }]} />
              <AppText variant="label" color={colors.muted} accessibilityRole="header">
                {t(`mealTypes.${group.type}`)}
              </AppText>
            </View>
            <Card flush>
              {group.items.map((meal, index) => (
                <MealRow key={meal.id} meal={meal} divider={index > 0} onPress={() => openMeal(meal)} />
              ))}
            </Card>
          </View>
        ))}

        {meals.length > 0 ? (
          <View style={styles.chips}>
            <Chip icon="copy" label={t('copy.yesterday')} onPress={copyFromYesterday} />
            <Chip icon="corner-up-right" label={t('copy.entireDay')} onPress={copyToTomorrow} />
          </View>
        ) : null}
      </Section>

      <WaterToday day={day} target={goal?.water_ml ?? null} />

      {goals.enabled && summary ? (
        <Disclosure label={t('home.goalDetails')} testID="goal-details">
          <GoalDashboard summary={summary} goal={goal} hideWater={tracking.enabled === true} onEdit={() => router.push('/goals')} />
        </Disclosure>
      ) : null}

      <View style={styles.tools}>
        {tools.map((tool, index) => (
          <Pressable
            key={tool.key}
            testID={`tool-${tool.key}`}
            accessibilityRole="button"
            accessibilityLabel={tool.label}
            onPress={tool.onPress}
            style={({ pressed }) => [
              styles.tool,
              // An odd last tile takes the whole row instead of leaving a gap.
              index === tools.length - 1 && tools.length % 2 === 1 && styles.toolWide,
              pressed && styles.toolPressed,
            ]}>
            <Icon name={tool.icon} size={20} color={colors.sage} />
            <AppText variant="label">{tool.label}</AppText>
          </Pressable>
        ))}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.xs,
    gap: spacing.sm,
  },
  actions: { flexDirection: 'row', alignItems: 'center' },
  spinner: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  today: { alignSelf: 'center' },
  group: { gap: spacing.xs + 2 },
  groupHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.xs },
  groupDot: { width: 10, height: 10, borderRadius: 5 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, paddingTop: spacing.xs },
  tools: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tool: {
    flexGrow: 1,
    flexBasis: '45%',
    minHeight: touch + spacing.xl,
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    justifyContent: 'center',
  },
  toolWide: { flexBasis: '100%' },
  toolPressed: { backgroundColor: colors.field },
});
