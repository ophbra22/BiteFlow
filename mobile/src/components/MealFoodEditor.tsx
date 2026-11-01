import { useEffect, useRef, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

import type { NutritionReference } from '@/api/meal-analysis-types';
import { errorMessageKey } from '@/api/messages';
import { foodTotals, foodValid, per100, replaceReference, type ReviewFood } from '@/domain/meal-analysis';
import { NUTRIENTS } from '@/domain/nutrition';
import { applyLabelServing } from '@/domain/servings';
import { correctBasis } from '@/domain/unified-review';
import { validateAmount, validateFoodName, validateNutrient } from '@/domain/validation';
import { useI18n } from '@/i18n/I18nProvider';
import type { TKey } from '@/i18n/translate';
import { haptics } from '@/native/haptics';
import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Button } from './Button';
import { Card } from './Card';
import { Disclosure } from './Disclosure';
import { Notice } from './Notice';
import { NutritionGrid } from './NutritionGrid';
import { Segmented } from './Segmented';
import { ServingSelector, type ServingLoader } from './ServingSelector';
import { TextField } from './TextField';

type Props = {
  servings?: ServingLoader;
  food: ReviewFood;
  onChange: (food: ReviewFood) => void;
  onRemove: () => void;
  partial?: boolean;
  disabled: boolean;
  search: (q: string) => Promise<{ foods: NutritionReference[] }>;
};

/** One food in a meal. What most people check stays open; sources and corrections sit one tap away. */
export function MealFoodEditor({ food, onChange, onRemove, disabled, search, partial = false, servings }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NutritionReference[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<TKey | null>(null);
  const request = useRef(0);
  useEffect(
    () => () => {
      request.current += 1;
    },
    [],
  );
  const change = (patch: Partial<ReviewFood>) => onChange({ ...food, ...patch, confirmed: false });
  const find = async (text = query) => {
    if (text.trim().length < 2) return;
    const version = ++request.current;
    setBusy(true);
    setFailure(null);
    setResults(null);
    try {
      const response = await search(text.trim());
      if (request.current === version) setResults(response.foods);
    } catch (error) {
      if (request.current === version) setFailure(errorMessageKey(error));
    } finally {
      if (request.current === version) setBusy(false);
    }
  };
  const choose = (record: NutritionReference) => {
    onChange(replaceReference(food, record));
    setOpen(false);
    setResults(null);
  };
  const amountNumber = Number(food.amount.replace(',', '.'));
  const amountError = partial && amountNumber >= 0.0001 && amountNumber <= 2000 ? null : validateAmount(food.amount);
  const nameError = validateFoodName(food.name);
  return (
    <Card testID={`food-editor-${food.id}`}>
      {food.region ? (
        <AppText variant="caption" color={colors.muted}>
          {t('analysis.region', { region: food.region })}
        </AppText>
      ) : null}
      <TextField
        label={t('review.food')}
        value={food.name}
        maxLength={120}
        editable={!disabled}
        onChangeText={(name) => change({ name })}
        error={nameError ? t(nameError) : null}
      />
      <View style={styles.meta}>
        <AppText variant="caption" color={colors.muted}>
          {t('analysis.confidence', { level: t(`analysis.${food.confidence}`) })}
        </AppText>
        {food.range ? (
          <AppText variant="caption" color={colors.muted}>
            {t('analysis.estimateRange', { low: food.range[0], high: food.range[1] })}
          </AppText>
        ) : null}
      </View>
      {food.question ? <Notice tone="warning" message={food.question} /> : null}
      <TextField
        testID={`food-weight-${food.id}`}
        label={partial ? `${t('review.amount')} (${food.basis ?? 'g'})` : t('analysis.amount')}
        hint={partial ? t('unified.amountHint') : t('analysis.amountHint')}
        value={food.amount}
        onChangeText={(amount) => change({ amount, originalPortion: undefined })}
        editable={!disabled}
        maxLength={12}
        keyboardType="decimal-pad"
        ltr
        error={amountError ? t(amountError) : null}
      />
      {partial ? (
        <Segmented
          label={t('unified.basis')}
          value={food.basis ?? 'g'}
          disabled={disabled}
          options={[
            { value: 'g', label: 'g' },
            { value: 'ml', label: 'ml' },
          ]}
          onChange={(basis) => onChange(correctBasis(food, basis))}
        />
      ) : null}
      {partial && servings ? <ServingSelector food={food} onChange={onChange} disabled={disabled} load={servings} /> : null}
      {food.basisCorrection ? (
        <View testID="original-nutrition-basis" style={styles.stack}>
          <Notice message={t('basisCorrection.manual')} />
          <AppText variant="caption">
            {t('basisCorrection.basis', { original: food.basisCorrection.original_nutrition_per_100.basis, current: food.basis ?? 'g' })}
          </AppText>
          <AppText variant="caption">
            {food.basisCorrection.original_source.provider} · {food.basisCorrection.original_source.reference_id ?? t('recipes.unknown')}
          </AppText>
          <AppText variant="caption">
            {food.basisCorrection.original_source.version ?? ''} · {t(`tracking.statusLabels.${food.basisCorrection.original_source.verified_status}` as TKey)}
          </AppText>
          {Object.entries(food.basisCorrection.original_nutrition_per_100)
            .filter(([key]) => key !== 'basis')
            .map(([key, value]) => (
              <AppText variant="caption" key={key}>
                {t(`basisCorrection.${key}` as TKey)}: {value == null ? t('recipes.unknown') : String(value)}
              </AppText>
            ))}
        </View>
      ) : null}

      <NutritionGrid values={foodTotals(food)} />

      {food.product ? (
        <>
          <AppText variant="caption" color={colors.muted}>
            {food.product.brand} · {food.product.barcode} · {food.product.quantity}
          </AppText>
          {food.product.servingQuantity ? (
            <Button
              compact
              kind="ghost"
              label={t('unified.serving', { amount: food.product.servingQuantity, unit: food.basis ?? 'g' })}
              disabled={disabled || food.product.servingQuantity > 2000 || food.product.servingQuantity < 0.0001}
              onPress={() => onChange(applyLabelServing(food))}
            />
          ) : null}
          {food.product.notes.map((note, i) => (
            <AppText key={i} variant="caption" color={colors.muted}>
              {note}
            </AppText>
          ))}
        </>
      ) : null}

      <View style={styles.source}>
        <AppText variant="label" color={colors.muted}>
          {t('analysis.reference')}
        </AppText>
        {food.reference && !food.manual ? (
          <>
            <AppText variant="caption">{food.reference.name}</AppText>
            <Button
              compact
              label={`${food.reference.source} · ${food.reference.id}`}
              kind="ghost"
              onPress={() => Linking.openURL(food.reference!.source_url)}
            />
          </>
        ) : food.manual ? (
          <AppText variant="caption">{food.source ?? t('analysis.manualSource')}</AppText>
        ) : (
          <Notice tone="warning" message={t('analysis.missing')} />
        )}
      </View>

      {food.manual ? (
        <View style={styles.fields}>
          {NUTRIENTS.map((k) => {
            const error = partial && !(food.manual![k] ?? '').trim() ? null : validateNutrient(k, food.manual![k] ?? '');
            return (
              <View style={styles.field} key={k}>
                <TextField
                  label={`${t(`nutrients.${k}`)} · ${t(food.basis === 'ml' ? 'units.per100ml' : 'units.per100g')}`}
                  value={food.manual![k] ?? ''}
                  onChangeText={(value) => change({ manualOverride: true, manual: { ...food.manual!, [k]: value } })}
                  keyboardType="decimal-pad"
                  ltr
                  maxLength={12}
                  editable={!disabled}
                  error={error ? t(error) : null}
                />
              </View>
            );
          })}
        </View>
      ) : null}

      <Button
        testID={`confirm-${food.id}`}
        label={t(food.confirmed ? 'analysis.confirmed' : 'analysis.confirm')}
        icon={food.confirmed ? 'check' : undefined}
        kind={food.confirmed ? 'secondary' : 'primary'}
        disabled={disabled || !foodValid(food, partial)}
        onPress={() => {
          haptics.tap();
          onChange({ ...food, confirmed: !food.confirmed });
        }}
      />

      <Disclosure label={t('analysis.corrections')} testID={`food-more-${food.id}`} initiallyOpen={open}>
        {food.alternatives.length ? (
          <View style={styles.stack}>
            <AppText variant="caption" color={colors.muted}>
              {t('analysis.alternatives')}
            </AppText>
            {food.alternatives.map((name, index) => (
              <Button
                key={`${index}-${name}`}
                compact
                kind="ghost"
                label={name}
                disabled={disabled || busy}
                onPress={() => {
                  setOpen(true);
                  setQuery(name);
                  void find(name);
                }}
              />
            ))}
          </View>
        ) : null}
        <Button
          compact
          kind="secondary"
          label={t('analysis.replace')}
          disabled={disabled}
          onPress={() => {
            setOpen((value) => !value);
            setQuery(food.name);
          }}
        />
        {open ? (
          <View style={styles.stack}>
            <TextField
              label={t('analysis.search')}
              hint={t('analysis.searchHint')}
              value={query}
              onChangeText={setQuery}
              maxLength={160}
              editable={!disabled}
              returnKeyType="search"
              onSubmitEditing={() => find()}
            />
            <Button
              compact
              label={t('analysis.search')}
              busyLabel={t('analysis.searching')}
              busy={busy}
              kind="secondary"
              disabled={disabled || query.trim().length < 2}
              onPress={() => find()}
            />
            {failure ? <Notice tone="error" message={t(failure)} /> : null}
            {results?.length === 0 ? <Notice message={t('analysis.noResults')} /> : null}
            {(results ?? food.references).map((record) => (
              <Button
                compact
                key={record.id}
                label={`${record.name} · ${record.data_type} · ${record.id}`}
                kind="ghost"
                disabled={disabled}
                onPress={() => choose(record)}
              />
            ))}
          </View>
        ) : null}
        {!food.manual ? (
          <Button
            compact
            kind="ghost"
            label={t('analysis.manual')}
            disabled={disabled}
            onPress={() => {
              const values = per100(food);
              change({
                manualOverride: true,
                manual: Object.fromEntries(
                  NUTRIENTS.map((k) => [k, values[k] === null ? '' : String(values[k])]),
                ) as NonNullable<ReviewFood['manual']>,
              });
            }}
          />
        ) : null}
        <Button compact kind="danger" icon="trash-2" label={t('analysis.remove')} disabled={disabled} onPress={onRemove} />
      </Disclosure>
    </Card>
  );
}

const styles = StyleSheet.create({
  meta: { gap: 2 },
  source: { gap: spacing.xs },
  stack: { gap: spacing.sm },
  fields: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  field: { flexBasis: '45%', flexGrow: 1, minWidth: 135 },
});
