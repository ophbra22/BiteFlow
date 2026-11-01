import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import type { LibraryStore } from '@/data/library-store';
import type { LibraryEntry } from '@/domain/library';
import { parseDecimal } from '@/domain/validation';
import { useI18n } from '@/i18n/I18nProvider';
import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { Button } from './Button';
import { Card } from './Card';
import { Chip } from './Chip';
import { EmptyState } from './EmptyState';
import { Notice } from './Notice';
import { Segmented } from './Segmented';
import { Skeleton } from './Skeleton';
import { TextField } from './TextField';

export function LibraryPanel({
  store,
  onSelect,
  recipes = false,
  onEdit,
}: {
  store: LibraryStore;
  onSelect: (entry: LibraryEntry, servings: number) => void | Promise<void>;
  recipes?: boolean;
  onEdit?: (entry: LibraryEntry) => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<'recent' | 'favorites'>('recent');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [amount, setAmount] = useState('1');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const busyRef = useRef(false);
  const favorites = !recipes && tab === 'favorites';
  const state = useSyncExternalStore(store.subscribe, () => store.get(favorites, search, offset));
  useEffect(() => {
    void store.load(favorites, search, offset);
  }, [store, favorites, search, offset]);
  const servings = parseDecimal(amount);
  const valid = servings !== null && Number.isFinite(servings) && servings >= 0.01 && servings <= 1000;
  const perform = async (action: () => void | Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const runSearch = () => {
    setSearch(query.trim());
    setOffset(0);
  };
  return (
    <>
      {!recipes ? (
        <Segmented
          label={t('library.title')}
          value={tab}
          onChange={(value) => {
            setTab(value);
            setOffset(0);
          }}
          disabled={busy}
          options={[
            { value: 'recent', label: t('library.recents') },
            { value: 'favorites', label: t('library.favorites') },
          ]}
        />
      ) : null}
      <TextField
        label={t('library.search')}
        value={query}
        onChangeText={setQuery}
        maxLength={120}
        editable={!busy}
        returnKeyType="search"
        onSubmitEditing={runSearch}
      />
      <Button compact kind="secondary" icon="search" label={t('library.search')} disabled={busy} onPress={runSearch} />
      {state.enabled === false ? <Notice message={t('library.disabled')} /> : null}
      {state.data && !state.fresh ? <Notice tone="warning" message={t('library.stale')} /> : null}
      {state.error || error ? (
        <Notice tone="error" message={t(errorMessageKey(error ?? state.error))}>
          <Button
            compact
            kind="ghost"
            label={t('common.retry')}
            disabled={busy || state.loading}
            onPress={() => store.refresh(favorites, search, offset)}
          />
        </Notice>
      ) : null}
      <TextField
        testID="library-servings"
        label={t('library.servings')}
        hint={t('library.servingsHint')}
        value={amount}
        onChangeText={setAmount}
        editable={!busy}
        keyboardType="decimal-pad"
        ltr
        maxLength={12}
        error={!valid ? t('library.invalidAmount') : null}
      />
      {state.loading && !state.data ? (
        <Card accessibilityLabel={t('common.loading')}>
          <Skeleton height={24} width="70%" />
          <Skeleton height={44} />
        </Card>
      ) : null}
      {state.data?.items.length === 0 ? <EmptyState icon="repeat" title={t('library.empty')} /> : null}
      {state.data?.items.map((entry) => (
        <Card key={entry.kind + entry.id}>
          <View style={styles.title}>
            <AppText variant="bodyStrong">{entry.name}</AppText>
            <AppText variant="caption" color={colors.muted}>
              {t(entry.kind === 'recipe' ? 'library.recipe' : 'library.snapshot')}
            </AppText>
          </View>
          <Button
            compact
            testID={'repeat-' + entry.id}
            icon="repeat"
            label={t('library.repeat')}
            disabled={!valid || busy}
            onPress={() => perform(() => onSelect(entry, servings!))}
          />
          <View style={styles.row}>
            <Chip
              icon="star"
              selected={entry.favorite}
              label={t(entry.favorite ? 'library.unfavorite' : 'library.favorite')}
              disabled={busy || !state.fresh}
              onPress={() => perform(() => store.favorite(entry, !entry.favorite))}
            />
            {onEdit ? <Chip icon="edit-2" label={t('recipes.edit')} onPress={() => onEdit(entry)} disabled={busy} /> : null}
          </View>
        </Card>
      ))}
      {offset > 0 ? (
        <Button compact kind="secondary" label={t('library.previous')} disabled={busy} onPress={() => setOffset(Math.max(0, offset - 20))} />
      ) : null}
      {state.data?.next_offset != null ? (
        <Button compact kind="secondary" label={t('library.more')} disabled={busy} onPress={() => setOffset(state.data!.next_offset!)} />
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  title: { gap: 2 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
