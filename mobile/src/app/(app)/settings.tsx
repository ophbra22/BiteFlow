import Constants from 'expo-constants';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, StyleSheet, View } from 'react-native';

import { useAuth } from '@/auth/AuthProvider';
import { AccountExport } from '@/components/AccountExport';
import { AppleSignInButton } from '@/components/AppleSignInButton';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Header } from '@/components/Header';
import { ListRow } from '@/components/ListRow';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { Section } from '@/components/Section';
import { Segmented } from '@/components/Segmented';
import { ServerSettings } from '@/components/ServerSettings';
import { WidgetSettings } from '@/components/WidgetSettings';
import { ALLOW_SERVER_OVERRIDE } from '@/config/env';
import { useDraft } from '@/data/DraftProvider';
import { useI18n } from '@/i18n/I18nProvider';
import { ltr } from '@/i18n/format';
import { habitsText } from '@/i18n/habits';
import type { Language } from '@/i18n/translate';
import { isHealthConnect } from '@/native/health/platform';
import { colors, spacing } from '@/theme/tokens';

export default function Settings() {
  const { t, language, setLanguage } = useI18n();
  const { user, signOut, linkApple } = useAuth();
  const { draft } = useDraft();
  const [switching, setSwitching] = useState(false);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const changeLanguage = async (next: Language) => {
    if (next === language || switching) return;
    setSwitching(true);
    // The draft is already on disk, so the reload that flips the layout loses nothing.
    const result = await setLanguage(next);
    if (result === 'restart-needed') setRestartNeeded(true);
    if (result !== 'reloading') setSwitching(false);
  };

  const confirmSignOut = () =>
    Alert.alert(
      t('settings.signOutTitle'),
      `${t('settings.signOutBody')}${draft ? `\n\n${t('settings.signOutUnsaved')}` : ''}`,
      [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('settings.signOut'),
          style: 'destructive',
          onPress: async () => {
            setSigningOut(true);
            await signOut();
          },
        },
      ],
    );

  return (
    <Screen header={<Header title={t('settings.title')} />}>
      <Section title={t('settings.account')}>
        <Card>
          <View accessible accessibilityLabel={`${t('settings.signedInAs')} ${user?.username ?? ''}`}>
            <AppText variant="caption" color={colors.muted}>
              {t('settings.signedInAs')}
            </AppText>
            <AppText testID="account-name" variant="heading">
              {ltr(user?.username ?? '')}
            </AppText>
          </View>
          {Platform.OS === 'ios' &&
            (user?.apple_linked ? (
              <Notice tone="success" message={t('apple.linked')} />
            ) : (
              <>
                <AppText variant="caption" color={colors.muted}>
                  {t('apple.linkHint')}
                </AppText>
                <AppleSignInButton onPress={linkApple} disabled={signingOut} />
              </>
            ))}
          <Button
            compact
            testID="sign-out"
            kind="secondary"
            icon="log-out"
            label={t('settings.signOut')}
            busy={signingOut}
            onPress={confirmSignOut}
          />
        </Card>
      </Section>

      <Section title={t('settings.preferences')}>
        <Card>
          <Segmented
            label={t('settings.language')}
            value={language}
            onChange={changeLanguage}
            disabled={switching}
            options={[
              { value: 'he', label: t('settings.hebrew') },
              { value: 'en', label: t('settings.english') },
            ]}
          />
          <AppText variant="caption" color={colors.muted}>
            {t('settings.languageNote')}
          </AppText>
          {restartNeeded ? <Notice tone="warning" message={t('settings.restartNeeded')} /> : null}
        </Card>
        <Card flush>
          <ListRow icon="target" title={t('goals.title')} onPress={() => router.push('/goals')} />
          <ListRow divider icon="bell" title={habitsText(language, 'title')} onPress={() => router.push('/reminders')} />
          <ListRow
            divider
            icon="heart"
            title={isHealthConnect ? 'Health Connect' : language === 'he' ? 'בריאות Apple' : 'Apple Health'}
            onPress={() => router.push('/health')}
          />
          <ListRow divider icon="book" title={t('recipes.title')} onPress={() => router.push('/recipes')} />
        </Card>
        <WidgetSettings />
      </Section>

      <Section title={t('settings.yourData')}>
        <AccountExport />
        <Card flush>
          <ListRow
            testID="delete-account"
            destructive
            icon="trash-2"
            title={t('settings.deleteAccount')}
            onPress={() => router.push('/delete-account')}
          />
        </Card>
      </Section>

      {ALLOW_SERVER_OVERRIDE ? <ServerSettings /> : null}

      <Section title={t('settings.about')}>
        <View style={styles.about}>
          <AppText variant="caption" color={colors.muted}>
            {t('settings.privacyNote')}
          </AppText>
          <AppText variant="caption" color={colors.muted}>
            {t('settings.nutritionNote')}
          </AppText>
          <AppText variant="caption" color={colors.muted}>
            {t('settings.version')} {ltr(Constants.expoConfig?.version ?? '')}
          </AppText>
        </View>
      </Section>
    </Screen>
  );
}

const styles = StyleSheet.create({
  about: { gap: spacing.sm },
});
