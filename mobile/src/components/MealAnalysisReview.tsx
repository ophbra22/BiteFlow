import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import { useAuth } from '@/auth/AuthProvider';
import { DraftPersistenceNotice } from '@/components/DraftPersistenceNotice';
import { useDraft } from '@/data/DraftProvider';
import { validateTimeContext } from '@/domain/canonical';
import { analysisValid, mealTotals, newReviewFood, type AnalysisDraft } from '@/domain/meal-analysis';
import { MEAL_TYPES } from '@/domain/nutrition';
import { useI18n } from '@/i18n/I18nProvider';
import type { TKey } from '@/i18n/translate';
import { haptics } from '@/native/haptics';
import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Button } from './Button';
import { Card } from './Card';
import { DayNav } from './DayNav';
import { Disclosure } from './Disclosure';
import { Header } from './Header';
import { MealFoodEditor } from './MealFoodEditor';
import { Notice } from './Notice';
import { NutritionGrid } from './NutritionGrid';
import { PrivateProductSave } from './PrivateProductSave';
import { Screen } from './Screen';
import { Section } from './Section';
import { Segmented } from './Segmented';
import { TextField } from './TextField';
import { useToast } from './Toast';

const WARNINGS: Record<string, TKey> = {
  conflicting_energy_units: 'label.energyConflict',
  conflicting_sodium_salt: 'label.sodiumConflict',
  exact_barcode_unavailable: 'label.exactUnavailable',
  text_ai_disabled: 'text.aiUnavailable',
  text_ai_unavailable: 'text.aiUnavailable',
  text_ai_quota: 'text.aiUnavailable',
  historical_snapshot_scaling: 'library.snapshotWarning',
  estimated_portions: 'analysis.warnings.estimated_portions',
  hidden_ingredients: 'analysis.warnings.hidden_ingredients',
  missing_nutrition: 'analysis.warnings.missing_nutrition',
  poor_lighting: 'analysis.warnings.poor_lighting',
  low_detail: 'analysis.warnings.low_detail',
};

/** The shared last step of every way to add a meal: check each food, then save. */
export function MealAnalysisReview() {
  const { t } = useI18n();
  const { api } = useAuth();
  const { draft, update, save, saving, discard, newKey } = useDraft();
  const [privateSaving, setPrivateSaving] = useState(false);
  const pendingEdit = !!draft?.edit && draft.attempted;
  const blocked = saving || privateSaving || pendingEdit;
  const [failure, setFailure] = useState<TKey | null>(null);
  const toast = useToast();
  if (!draft?.analysis) return null;
  const analysis = draft.analysis;
  const updateAnalysis = (value: AnalysisDraft) => update({ analysis: value });
  const totals = mealTotals(analysis.foods);
  const onSave = async () => {
    if (saving || privateSaving || draft?.edit?.rejected) return;
    if (!validateTimeContext(draft.day, draft.occurredAt?.trim() || null, draft.timezoneId?.trim() || null)) {
      setFailure('unified.timeInvalid');
      haptics.warning();
      return;
    }
    if (!analysisValid(analysis)) {
      setFailure('analysis.needsReview');
      haptics.warning();
      return;
    }
    setFailure(null);
    try {
      await save();
      toast(t('review.saved'));
      router.dismissTo('/');
    } catch (error) {
      setFailure(errorMessageKey(error, 'saveCustom'));
      haptics.warning();
    }
  };
  return (
    <Screen
      header={
        <Header
          title={t(draft.edit ? 'mealEdit.title' : 'analysis.review')}
          leading="close"
          onLeading={() => router.dismissTo('/')}
        />
      }
      footer={
        <>
          {failure ? <Notice tone="error" message={t(failure)} /> : null}
          <Button
            testID="save-analyzed-meal"
            label={t(draft.edit ? (pendingEdit ? 'mealEdit.retry' : 'mealEdit.save') : 'review.save')}
            busyLabel={t('review.saving')}
            busy={saving}
            disabled={privateSaving || !!draft.edit?.rejected}
            onPress={onSave}
            icon="check"
          />
        </>
      }>
      <DraftPersistenceNotice />
      {pendingEdit ? <Notice tone="warning" message={t(draft.edit?.rejected ? 'mealEdit.conflict' : 'mealEdit.pending')} /> : null}
      {draft.edit?.rejected ? (
        <Button
          label={t('mealEdit.reload')}
          onPress={() =>
            Alert.alert(t('mealEdit.reload'), t('mealEdit.reloadHint'), [
              { text: t('common.cancel'), style: 'cancel' },
              {
                text: t('mealEdit.reload'),
                style: 'destructive',
                onPress: () => {
                  void discard().then(() =>
                    router.replace({
                      pathname: '/meal/edit/[id]',
                      params: { id: draft.edit!.groupId, day: draft.edit!.originalDate, kind: 'group' },
                    }),
                  );
                },
              },
            ])
          }
        />
      ) : null}

      <Card>
        <View style={styles.title}>
          <AppText variant="heading">{analysis.mealName}</AppText>
          {draft.origin === 'photo' ? (
            <AppText variant="caption" color={colors.muted}>
              {t('analysis.estimated')}
            </AppText>
          ) : null}
        </View>
        <AppText variant="label" color={colors.muted}>
          {t('analysis.total')}
        </AppText>
        <NutritionGrid values={totals} />
      </Card>

      {Object.values(totals).some((v) => v === null) ? <Notice tone="warning" message={t('analysis.incomplete')} /> : null}
      {analysis.warnings.length ? (
        <View style={styles.warnings}>
          {analysis.warnings.map((warning, i) => (
            <AppText key={i} variant="caption" color={colors.muted}>
              {WARNINGS[warning] ? t(WARNINGS[warning]) : warning}
            </AppText>
          ))}
        </View>
      ) : null}

      {analysis.foods.map((food) => (
        <MealFoodEditor
          servings={api.servings}
          key={food.id}
          food={food}
          disabled={blocked}
          partial={analysis.version === 2}
          search={api.nutritionReferences}
          onChange={(next) => updateAnalysis({ ...analysis, foods: analysis.foods.map((f) => (f.id === next.id ? next : f)) })}
          onRemove={() => updateAnalysis({ ...analysis, foods: analysis.foods.filter((f) => f.id !== food.id) })}
        />
      ))}
      {analysis.version === 2 && analysis.foods.length === 1 && !draft.edit ? (
        <PrivateProductSave
          key={draft.key}
          draft={draft}
          disabled={saving}
          onBusyChange={setPrivateSaving}
          onSaved={(product) =>
            updateAnalysis({
              ...analysis,
              foods: analysis.foods.map((food) => ({
                ...food,
                source: 'private_product',
                originSource: {
                  provider: 'private_product',
                  reference_id: product.id,
                  version: String(product.version),
                  verified_status: 'user_confirmed',
                },
              })),
            })
          }
        />
      ) : null}
      <Button
        compact
        label={t('analysis.addFood')}
        kind="secondary"
        disabled={blocked || analysis.foods.length >= 15}
        onPress={() =>
          updateAnalysis({
            ...analysis,
            foods: [...analysis.foods, { ...newReviewFood(newKey()), manual: { calories: '', protein: '', carbs: '', fat: '' } }],
          })
        }
        icon="plus"
      />

      <Section title={t('review.when')}>
        <Segmented
          label={t('review.meal')}
          value={draft.mealType}
          disabled={blocked}
          onChange={(mealType) => update({ mealType })}
          options={MEAL_TYPES.map((value) => ({ value, label: t(`mealTypes.${value}`) }))}
        />
        <DayNav day={draft.day} onChange={(day) => !blocked && update({ day })} compact />
        {analysis.version === 2 ? (
          <Disclosure label={t('unified.exactTime')} testID="exact-time" initiallyOpen={!!(draft.occurredAt || draft.timezoneId)}>
            <TextField
              label={t('unified.time')}
              hint={t('unified.timeHint')}
              value={draft.occurredAt ?? ''}
              editable={!blocked}
              ltr
              onChangeText={(occurredAt) => update({ occurredAt })}
              maxLength={40}
            />
            <TextField
              label={t('unified.zone')}
              hint="Asia/Jerusalem"
              value={draft.timezoneId ?? ''}
              editable={!blocked}
              ltr
              onChangeText={(timezoneId) => update({ timezoneId })}
              maxLength={80}
            />
          </Disclosure>
        ) : null}
      </Section>

      <Button
        compact
        label={t('review.discard')}
        kind="ghost"
        disabled={saving || privateSaving || (pendingEdit && !draft.edit?.rejected)}
        onPress={() =>
          Alert.alert(t('review.discardTitle'), t('review.discardBody'), [
            { text: t('common.cancel'), style: 'cancel' },
            {
              text: t('review.discard'),
              style: 'destructive',
              onPress: () => {
                void discard();
              },
            },
          ])
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { gap: spacing.xs },
  warnings: { gap: spacing.xs },
});
