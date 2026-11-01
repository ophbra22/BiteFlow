import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Header } from '@/components/Header';
import { Icon, IconName } from '@/components/Icon';
import { ListRow } from '@/components/ListRow';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { Section } from '@/components/Section';
import { useDraft } from '@/data/DraftProvider';
import { getAddIntent } from '@/data/add-intent';
import { useCatalog } from '@/data/catalog';
import { manualDraft, resumeDraftPath } from '@/domain/drafts';
import { useOnline } from '@/hooks/useOnline';
import { useI18n } from '@/i18n/I18nProvider';
import { foodName } from '@/i18n/translate';
import { colors, radius, spacing } from '@/theme/tokens';

type Option = { key: string; icon: IconName; title: string; hint: string; onPress: () => void };

/** Step 1 of adding a meal: the fastest ways first, everything else one glance below. */
export default function AddMethods() {
  const { t, language } = useI18n();
  const online = useOnline();
  const { draft, start, discard, newKey } = useDraft();
  const { foods } = useCatalog();

  const camera: Option = {
    key: 'camera',
    icon: 'camera',
    title: t('add.camera'),
    hint: t('add.cameraHint'),
    onPress: () => router.push({ pathname: '/add/photo', params: { source: 'camera' } }),
  };
  const quick: Option[] = [
    {
      key: 'barcode',
      icon: 'maximize',
      title: t('add.barcode'),
      hint: t('add.barcodeHint'),
      onPress: () => router.push('/add/barcode'),
    },
    { key: 'text', icon: 'edit-3', title: t('text.title'), hint: t('text.hint'), onPress: () => router.push('/add/text') },
    ...(process.env.EXPO_PUBLIC_VOICE_ENABLED === '1'
      ? [{ key: 'voice', icon: 'mic' as const, title: t('text.voiceTitle'), hint: t('voice.hint'), onPress: () => router.push('/add/voice') }]
      : []),
    { key: 'quick', icon: 'repeat', title: t('library.title'), hint: t('library.hint'), onPress: () => router.push('/library') },
  ];
  const more: Option[] = [
    {
      key: 'library',
      icon: 'image',
      title: t('add.library'),
      hint: t('add.libraryHint'),
      onPress: () => router.push({ pathname: '/add/photo', params: { source: 'library' } }),
    },
    {
      key: 'catalog',
      icon: 'list',
      title: t('add.catalog'),
      hint: foods ? t('add.catalogHint', { count: foods.length }) : t('catalog.estimateNote'),
      onPress: () => router.push('/add/catalog'),
    },
    { key: 'label', icon: 'file-text', title: t('label.title'), hint: t('label.hint'), onPress: () => router.push('/add/label') },
    { key: 'private', icon: 'archive', title: t('label.private'), hint: t('label.privateHint'), onPress: () => router.push('/add/private-products') },
    { key: 'recipes', icon: 'book', title: t('recipes.title'), hint: t('recipes.create'), onPress: () => router.push('/recipes') },
    {
      key: 'manual',
      icon: 'edit-2',
      title: t('add.manual'),
      hint: t('add.manualHint'),
      onPress: async () => {
        await start(manualDraft(newKey(), getAddIntent()));
        router.push('/add/review');
      },
    },
  ];

  const draftName = draft
    ? draft.foodId
      ? foodName(language, draft.foodId, draft.name)
      : draft.name.trim() || t('add.untitled')
    : '';

  return (
    <Screen header={<Header title={t('add.title')} leading="close" onLeading={() => router.dismissTo('/')} />}>
      {!online ? <Notice tone="warning" icon="wifi-off" title={t('states.offline')} message={t('states.needsConnection')} /> : null}
      {draft ? (
        <Notice tone="warning" icon="edit-3" title={t('add.resumeTitle')} message={t('add.resumeBody', { name: draftName })}>
          <Button label={t('add.resume')} onPress={() => router.push(resumeDraftPath(draft))} />
          <Button kind="ghost" label={t('add.discard')} onPress={discard} />
        </Notice>
      ) : null}
      <AppText variant="title" accessibilityRole="header">
        {t('add.question')}
      </AppText>

      <Pressable
        testID={`method-${camera.key}`}
        accessibilityRole="button"
        accessibilityLabel={camera.title}
        accessibilityHint={camera.hint}
        onPress={camera.onPress}
        style={({ pressed }) => [styles.lead, pressed && styles.leadPressed]}>
        <View style={styles.leadIcon}>
          <Icon name={camera.icon} size={26} color={colors.sage} />
        </View>
        <View style={styles.text}>
          <AppText variant="heading" color={colors.onSage}>
            {camera.title}
          </AppText>
          <AppText variant="caption" color={colors.onSage}>
            {camera.hint}
          </AppText>
        </View>
      </Pressable>

      <View style={styles.tiles}>
        {quick.map((option, index) => (
          <Pressable
            key={option.key}
            testID={`method-${option.key}`}
            accessibilityRole="button"
            accessibilityLabel={option.title}
            accessibilityHint={option.hint}
            onPress={option.onPress}
            style={({ pressed }) => [
              styles.tile,
              // An odd last tile takes the whole row instead of leaving a gap.
              index === quick.length - 1 && quick.length % 2 === 1 && styles.tileWide,
              pressed && styles.tilePressed,
            ]}>
            <Icon name={option.icon} size={22} color={colors.sage} />
            <AppText variant="bodyStrong">{option.title}</AppText>
            <AppText variant="caption" color={colors.muted} numberOfLines={3}>
              {option.hint}
            </AppText>
          </Pressable>
        ))}
      </View>

      <Section title={t('add.moreWays')}>
        <Card flush>
          {more.map((option, index) => (
            <ListRow
              key={option.key}
              testID={`method-${option.key}`}
              icon={option.icon}
              title={option.title}
              hint={option.hint}
              divider={index > 0}
              onPress={option.onPress}
            />
          ))}
        </Card>
      </Section>
    </Screen>
  );
}

const styles = StyleSheet.create({
  lead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.sage,
    padding: spacing.lg,
    minHeight: 88,
  },
  leadPressed: { opacity: 0.9, transform: [{ scale: 0.99 }] },
  leadIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.ground,
  },
  text: { flex: 1, gap: 2 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tile: {
    flexGrow: 1,
    flexBasis: '45%',
    gap: spacing.xs,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  tileWide: { flexBasis: '100%' },
  tilePressed: { backgroundColor: colors.field },
});
