import * as Crypto from 'expo-crypto';
import { router } from 'expo-router';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import { TrackingStore } from '@/data/tracking-store';
import { parseIsoDay, todayIso } from '@/domain/dates';
import {
  displayValue,
  localStamp,
  measurementContext,
  normalizeValue,
  stampInZone,
  type DisplayUnit,
  type Measurement,
  type TrackingKind,
} from '@/domain/tracking';
import { useI18n } from '@/i18n/I18nProvider';
import { formatDay, formatNumber, formatTime } from '@/i18n/format';
import { haptics } from '@/native/haptics';
import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Button } from './Button';
import { Card } from './Card';
import { Chip } from './Chip';
import { Disclosure } from './Disclosure';
import { EmptyState } from './EmptyState';
import { Meter } from './Meter';
import { Notice } from './Notice';
import { TextField } from './TextField';

export function TrackingPanel({
  kind,
  day,
  store,
  target,
  compact = false,
}: {
  kind: TrackingKind;
  day: string;
  store: TrackingStore;
  target: number | null;
  compact?: boolean;
}) {
  const { t, language } = useI18n();
  const state = useSyncExternalStore(store.subscribe, () => store.get(kind, day));
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [unit, setUnit] = useState<DisplayUnit>(kind === 'water' ? 'ml' : 'kg');
  const [amount, setAmount] = useState('');
  const [stamp, setStamp] = useState(localStamp(day === todayIso() ? new Date() : parseIsoDay(day)));
  const [timezone, setTimezone] = useState(zone);
  const [editing, setEditing] = useState<Measurement | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void store.load(kind, day);
  }, [store, kind, day]);
  const value = (n: number | null) => (n === null ? '—' : `${formatNumber(language, displayValue(n, unit), 1)} ${unit}`);
  const signed = (n: number | null) => (n === null ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${value(Math.abs(n))}`);
  const blocked = !state.writable || !state.fresh || state.saving || state.pending;
  async function save(quick?: number) {
    setError(null);
    try {
      const context =
        quick !== undefined
          ? measurementContext(localStamp(day === todayIso() ? new Date() : parseIsoDay(day)), zone)
          : measurementContext(stamp, timezone);
      const measured = quick ?? normalizeValue(Number(amount.replace(',', '.')), unit);
      await store.save(kind, { value: measured, ...context }, Crypto.randomUUID(), quick !== undefined ? null : editing);
      haptics.tap();
      setEditing(null);
      setAmount('');
    } catch (e) {
      setError(t(errorMessageKey(e)));
    }
  }
  async function erase(entry: Measurement) {
    setError(null);
    try {
      await store.save(
        kind,
        { value: entry.value, ...measurementContext(stampInZone(entry.occurred_at, entry.timezone_id), entry.timezone_id) },
        Crypto.randomUUID(),
        entry,
        true,
      );
    } catch (e) {
      setError(t(errorMessageKey(e)));
    }
  }
  if (state.enabled === false) return compact ? null : <Notice message={t('tracking.disabled')} />;
  const total = state.data?.total ?? null;
  const latest = state.data?.latest;
  const percent = total !== null && target ? (total / target) * 100 : null;
  const notices = (
    <>
      {state.saving ? <Notice message={t('tracking.pending')} /> : null}
      {!state.fresh && !state.loading && state.data ? (
        <Notice tone="warning" message={t('tracking.stale')}>
          <Button compact kind="ghost" label={t('common.retry')} disabled={state.saving} onPress={() => void store.load(kind, day)} />
        </Notice>
      ) : null}
      {error || state.error ? (
        <Notice tone="error" message={error ?? t(errorMessageKey(state.error))}>
          <Button compact kind="ghost" label={t('common.retry')} disabled={state.saving} onPress={() => void store.load(kind, day)} />
        </Notice>
      ) : null}
      {state.error ? <Notice tone="warning" message={t('tracking.rollback')} /> : null}
      {state.pending && !state.saving ? (
        <>
          <Notice message={t('tracking.retryHint')} />
          <Button
            compact
            label={t('tracking.retry')}
            onPress={() => {
              void store.retry().catch((e) => setError(t(errorMessageKey(e))));
            }}
          />
          {state.error && ['validation', 'conflict', 'notFound', 'forbidden'].includes(state.error.kind) ? (
            <Button
              compact
              kind="secondary"
              label={t('tracking.clearRejected')}
              onPress={() => {
                void store
                  .clearRejected()
                  .then(() => store.load(kind, day))
                  .catch((e) => setError(t(errorMessageKey(e))));
              }}
            />
          ) : null}
        </>
      ) : null}
    </>
  );
  const unitChip = (
    <Chip
      testID="tracking-unit"
      label={t('tracking.units', { unit })}
      disabled={!!editing}
      onPress={() => setUnit(unit === 'kg' ? 'lb' : unit === 'lb' ? 'kg' : unit === 'ml' ? 'fl oz' : 'ml')}
    />
  );
  return (
    <View style={styles.panel}>
      <Card>
        <View style={styles.title}>
          <AppText variant="section" style={styles.flex}>
            {t(`tracking.${kind}`)}
          </AppText>
          {compact ? null : unitChip}
        </View>
        {kind === 'water' ? (
          <>
            <AppText testID="water-total" variant="figure">
              {value(total)}
            </AppText>
            {percent !== null ? (
              <Meter
                accessible
                accessibilityRole="progressbar"
                accessibilityLabel={t('tracking.water')}
                accessibilityValue={{ min: 0, max: 100, now: Math.min(100, percent), text: `${formatNumber(language, percent, 1)}%` }}
                percent={percent}
              />
            ) : null}
            <AppText variant="caption" color={colors.muted}>
              {t('tracking.target', { value: value(target) })}
              {percent !== null ? `, ${formatNumber(language, percent, 1)}%` : ''}
            </AppText>
            <View style={styles.row}>
              {[150, 250, 500].map((ml) => (
                <Chip
                  key={ml}
                  testID={`water-add-${ml}`}
                  icon="plus"
                  label={value(ml)}
                  disabled={blocked}
                  onPress={() => {
                    void save(ml);
                  }}
                />
              ))}
              {compact ? (
                <Chip
                  icon="list"
                  label={t('tracking.history')}
                  onPress={() => router.push({ pathname: '/water', params: { day } })}
                />
              ) : null}
            </View>
          </>
        ) : (
          <>
            <AppText variant="figure">{value(latest?.value ?? null)}</AppText>
            {latest ? (
              <AppText variant="caption" color={colors.muted}>
                {t('tracking.latest', { value: value(latest.value) })}, {formatDay(language, latest.local_date)}, {t(`tracking.sources.${latest.source}`)}
              </AppText>
            ) : null}
            <AppText variant="label">{t('tracking.delta', { value: signed(state.data?.delta ?? null) })}</AppText>
            <AppText variant="caption" color={colors.muted}>
              {t('tracking.target', { value: value(target) })}
            </AppText>
          </>
        )}
      </Card>
      {notices}
      {compact ? null : (
        <>
          <Disclosure label={t(editing ? 'tracking.saveEdit' : 'tracking.customEntry')} initiallyOpen={kind === 'weight' || !!editing} key={editing?.id ?? 'new'}>
            <TextField
              label={t('tracking.amount', { unit })}
              value={amount}
              onChangeText={setAmount}
              keyboardType="decimal-pad"
              ltr
              editable={!state.saving && !state.pending}
            />
            <Disclosure label={t('unified.exactTime')} initiallyOpen={!!editing}>
              <TextField
                label={t('tracking.timestamp')}
                hint={t('tracking.timeHint')}
                value={stamp}
                onChangeText={setStamp}
                ltr
                editable={!state.saving && !state.pending}
              />
              <TextField
                label={t('tracking.zone')}
                value={timezone}
                onChangeText={setTimezone}
                ltr
                editable={!state.saving && !state.pending}
              />
            </Disclosure>
            <Button
              label={t(editing ? 'tracking.saveEdit' : 'tracking.add')}
              disabled={blocked}
              onPress={() => {
                void save();
              }}
            />
            {editing ? (
              <Button
                compact
                kind="ghost"
                label={t('common.cancel')}
                onPress={() => {
                  setEditing(null);
                  setAmount('');
                }}
              />
            ) : null}
          </Disclosure>
          <AppText variant="section" accessibilityRole="header">
            {t('tracking.history')}, {formatDay(language, day)}
          </AppText>
          <AppText variant="caption" color={colors.muted}>
            {t('tracking.pageLimit')}
          </AppText>
          {!state.data?.items.length ? <EmptyState icon={kind === 'water' ? 'droplet' : 'activity'} title={t('tracking.empty')} /> : null}
          {state.data?.items.length ? (
            <Card flush>
              {state.data.items.map((entry, index) => (
                <View key={entry.id} style={[styles.entry, index > 0 && styles.divider]}>
                  <View style={styles.entryText}>
                    <AppText variant="bodyStrong">{value(entry.value)}</AppText>
                    <AppText variant="caption" color={colors.muted}>
                      {formatTime(language, entry.occurred_at, entry.timezone_id)}
                      {entry.timezone_id === zone ? '' : `, ${entry.timezone_id}`}, {t(`tracking.sources.${entry.source}`)}
                    </AppText>
                  </View>
                  <View style={styles.row}>
                    <Chip
                      icon="edit-2"
                      label={t('tracking.edit')}
                      disabled={blocked || entry.source !== 'manual'}
                      onPress={() => {
                        setEditing(entry);
                        setAmount(String(displayValue(entry.value, unit)));
                        setStamp(stampInZone(entry.occurred_at, entry.timezone_id));
                        setTimezone(entry.timezone_id);
                      }}
                    />
                    <Chip
                      testID={`delete-${entry.id}`}
                      icon="trash-2"
                      label={t('tracking.delete')}
                      disabled={blocked}
                      onPress={() => {
                        void erase(entry);
                      }}
                    />
                  </View>
                </View>
              ))}
            </Card>
          ) : null}
          {state.data?.has_more ? (
            <Button
              compact
              kind="secondary"
              label={t('tracking.more')}
              onPress={() => {
                void store.load(kind, day, true);
              }}
            />
          ) : null}
          <View style={styles.row}>
            <Chip icon="bar-chart-2" label={t('tracking.trends')} onPress={() => router.push({ pathname: '/trends', params: { day } })} />
            <Chip icon="target" label={t('goals.edit')} onPress={() => router.push('/goals')} />
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { gap: spacing.md },
  title: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  entry: { padding: spacing.lg, gap: spacing.sm },
  entryText: { gap: 2 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
});
