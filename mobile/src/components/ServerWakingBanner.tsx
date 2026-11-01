import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useSyncExternalStore } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getServerWakingSnapshot, subscribeServerWaking } from '@/api/client';
import { useI18n } from '@/i18n/I18nProvider';
import { colors, spacing } from '@/theme/tokens';

const idleServerSnapshot = () => false;

/** A root-level consumer also covers GETs made while session restoration runs. */
export function ServerWakingBanner() {
  const waking = useSyncExternalStore(subscribeServerWaking, getServerWakingSnapshot, idleServerSnapshot);
  const { t, isRTL, language } = useI18n();
  useEffect(() => {
    // Navigator may still be waiting for the session GET behind the splash.
    if (waking) void SplashScreen.hideAsync().catch(() => {});
  }, [waking]);
  if (!waking) return null;
  const message = t('errors.serverWaking');
  return (
    <SafeAreaView edges={['top', 'left', 'right']} style={styles.safeArea}>
      <View accessible role="status" accessibilityLiveRegion="polite"
        accessibilityLabel={message} accessibilityLanguage={language}
        style={[styles.banner, { direction: isRTL ? 'rtl' : 'ltr' }]}>
        <Text style={[styles.text, { writingDirection: isRTL ? 'rtl' : 'ltr', textAlign: isRTL ? 'right' : 'left' }]}>
          {message}
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { backgroundColor: colors.surface },
  banner: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  text: { color: colors.sand, fontSize: 15 },
});