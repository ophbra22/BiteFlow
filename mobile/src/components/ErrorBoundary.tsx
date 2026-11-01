import type { ErrorBoundaryProps } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useState } from 'react';
import { I18nManager, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { loadInitialLanguage } from '@/i18n/I18nProvider';
import { type Language, translate } from '@/i18n/translate';
import { colors, radius, spacing, touch } from '@/theme/tokens';

/**
 * Expo Router wraps the root route in its React boundary when this component
 * is exported as ErrorBoundary. Keep the fallback independent of app providers,
 * custom fonts, auth state and the component that failed. Never show diagnostics.
 */
export function ErrorBoundary({ retry }: ErrorBoundaryProps) {
  const [language, setLanguage] = useState<Language>(I18nManager.isRTL ? 'he' : 'en');
  const [retrying, setRetrying] = useState(false);
  useEffect(() => {
    let mounted = true;
    void loadInitialLanguage().then(value => { if (mounted) setLanguage(value); }).catch(() => {});
    // Also cover a crash before Navigator has hidden the startup splash.
    void SplashScreen.hideAsync().catch(() => {});
    return () => { mounted = false; };
  }, []);
  const rtl = language === 'he';
  const textDirection = { textAlign: rtl ? 'right' : 'left', writingDirection: rtl ? 'rtl' : 'ltr' } as const;
  const reset = async () => {
    if (retrying) return;
    setRetrying(true);
    try { await retry(); } catch { /* Keep the recovery screen available. */ }
    finally { setRetrying(false); }
  };
  const retryLabel = translate(language, 'crash.retry');
  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <View testID="crash-recovery" style={[styles.content, { direction: rtl ? 'rtl' : 'ltr' }]}>
            <Text accessibilityRole="header" style={[styles.title, textDirection]}>{translate(language, 'crash.title')}</Text>
            <Text style={[styles.body, textDirection]}>{translate(language, 'crash.body')}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={retryLabel}
              accessibilityState={{ disabled: retrying, busy: retrying }} disabled={retrying}
              onPress={() => void reset()} style={styles.button}>
              <Text style={[styles.buttonText, textDirection]}>{retryLabel}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.ground },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl },
  content: { gap: spacing.lg, width: '100%', maxWidth: 560, alignSelf: 'center' },
  // System fonts and unrestricted text scaling remain usable if font loading fails.
  title: { fontSize: 28, fontWeight: '600', color: colors.sand },
  body: { fontSize: 17, color: colors.muted },
  button: { minHeight: touch, padding: spacing.lg, borderRadius: radius.md, backgroundColor: colors.sage, justifyContent: 'center' },
  buttonText: { fontSize: 17, fontWeight: '600', color: colors.onSage },
});