import { Link } from 'expo-router';
import { useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { errorMessageKey } from '@/api/messages';
import { useAuth } from '@/auth/AuthProvider';
import { AppText } from '@/components/AppText';
import { AuthDivider, AuthIntro, FormStack } from '@/components/AuthForm';
import { AppleSignInButton } from '@/components/AppleSignInButton';
import { Button } from '@/components/Button';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { TextField } from '@/components/TextField';
import { ALLOW_SERVER_OVERRIDE } from '@/config/env';
import { validatePassword, validateUsername } from '@/domain/validation';
import { useI18n } from '@/i18n/I18nProvider';
import { ltr } from '@/i18n/format';
import type { TKey } from '@/i18n/translate';
import { colors, spacing } from '@/theme/tokens';

export default function SignIn() {
  const { t } = useI18n();
  const { signIn, signInWithApple, sessionExpired, serverUrl } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<TKey | null>(null);

  const usernameError = validateUsername(username);
  const passwordError = validatePassword(password);

  const submit = async () => {
    setSubmitted(true);
    setFailure(null);
    if (usernameError || passwordError) return;
    setBusy(true);
    try {
      await signIn(username, password);
    } catch (error) {
      setFailure(errorMessageKey(error, 'signIn'));
      setBusy(false);
    }
  };

  return (
    <Screen>
      <AuthIntro title={t('auth.signInTitle')} body={t('auth.tagline')} />
      {sessionExpired && !failure ? <Notice tone="warning" message={t('auth.sessionExpired')} /> : null}
      {failure ? <Notice tone="error" message={t(failure)} /> : null}
      <AppleSignInButton onPress={signInWithApple} disabled={busy} />
      {/* The divider only makes sense where the Apple button can appear. */}
      {Platform.OS === 'ios' ? <AuthDivider label={t('apple.orPassword')} /> : null}
      <FormStack>
        <TextField
          testID="username"
          label={t('auth.username')}
          value={username}
          onChangeText={setUsername}
          error={submitted && usernameError ? t(usernameError) : null}
          ltr
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="username"
          textContentType="username"
          returnKeyType="next"
          editable={!busy}
        />
        <TextField
          testID="password"
          label={t('auth.password')}
          value={password}
          onChangeText={setPassword}
          error={submitted && passwordError ? t(passwordError) : null}
          ltr
          secret
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="current-password"
          textContentType="password"
          returnKeyType="go"
          onSubmitEditing={submit}
          editable={!busy}
        />
        <Button testID="submit" label={t('auth.signIn')} onPress={submit} busy={busy} />
      </FormStack>
      <View style={styles.links}>
        <Link href="/register" replace accessibilityRole="link">
          <AppText variant="bodyStrong" color={colors.sage} center>
            {t('auth.toRegister')}
          </AppText>
        </Link>
        <Link href="/recover" accessibilityRole="link">
          <AppText variant="body" color={colors.muted} center>
            {t('auth.toRecover')}
          </AppText>
        </Link>
        {ALLOW_SERVER_OVERRIDE ? (
          <Link href="/server" accessibilityRole="link">
            <AppText variant="caption" color={colors.muted} center>
              {t('settings.server')}: {ltr(serverUrl)}
            </AppText>
          </Link>
        ) : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  links: { gap: spacing.lg, alignItems: 'center', paddingTop: spacing.md },
});
