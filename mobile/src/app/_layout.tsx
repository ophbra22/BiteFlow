import {WidgetProvider} from '@/components/WidgetProvider';
import {Screen} from '@/components/Screen';
import {Notice} from '@/components/Notice';
import {Button} from '@/components/Button';
import {
  Fredoka_400Regular,
  Fredoka_500Medium,
  Fredoka_600SemiBold,
  useFonts,
} from '@expo-google-fonts/fredoka';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AuthProvider, useAuth } from '@/auth/AuthProvider';
import { ToastProvider } from '@/components/Toast';
import { DraftProvider } from '@/data/DraftProvider';
import { I18nProvider, loadInitialLanguage, useI18n } from '@/i18n/I18nProvider';
import { ensureDirection } from '@/i18n/direction';
import type { Language } from '@/i18n/translate';
import { colors } from '@/theme/tokens';

// Expo Router owns the root React error boundary and retry lifecycle.
export { ErrorBoundary } from '@/components/ErrorBoundary';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [language, setLanguage] = useState<Language | null>(null);
  const [fontsLoaded, fontError] = useFonts({
    Fredoka_400Regular,
    Fredoka_500Medium,
    Fredoka_600SemiBold,
  });

  useEffect(() => {
    (async () => {
      const initial = await loadInitialLanguage();
      // The splash screen stays up while the layout direction is matched to the language.
      const direction = await ensureDirection(initial);
      if (direction !== 'reloading') setLanguage(initial);
    })();
  }, []);

  // If the font files fail to load the app still opens, in the system font.
  if (!language || (!fontsLoaded && !fontError)) return null;
  return (
    <SafeAreaProvider>
      <I18nProvider initial={language}>
        <AuthProvider><WidgetProvider>
          <DraftProvider>
            <ToastProvider>
              <StatusBar style="light" />
              <Navigator />
            </ToastProvider>
          </DraftProvider>
        </WidgetProvider></AuthProvider>
      </I18nProvider>
    </SafeAreaProvider>
  );
}

function Navigator() {
  const { status, pendingRecoveryCode,widgetCleanupError,retryWidgetCleanup,privateCleanupError,retryPrivateCleanup } = useAuth();
  const {language}=useI18n();

  useEffect(() => {
    if (status !== 'loading'||widgetCleanupError||privateCleanupError) SplashScreen.hideAsync();
  }, [status,widgetCleanupError,privateCleanupError]);

  if(privateCleanupError)return <Screen><Notice tone="warning" message={language==='he'?'לא ניתן לנקות קבצים פרטיים זמניים. נסו שוב לפני פתיחת חשבון.':'Private temporary files could not be cleared. Retry before opening an account.'}/><Button label={language==='he'?'ניסיון נוסף':'Retry'} onPress={()=>void retryPrivateCleanup()}/></Screen>;
  if(widgetCleanupError)return <Screen><Notice tone="warning" message={language==='he'?'לא ניתן לנקות את נתוני הווידג׳ט. נסו שוב לפני פתיחת חשבון.':'Widget data could not be cleared. Retry before opening an account.'}/><Button label={language==='he'?'ניסיון נוסף':'Retry'} onPress={()=>void retryWidgetCleanup()}/></Screen>;
  if (status === 'loading') return null;
  const signedIn = status === 'signedIn';
  const mustSaveCode = signedIn && pendingRecoveryCode !== null;
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.ground } }}>
      <Stack.Protected guard={signedIn && !mustSaveCode}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
      {/* A new recovery code is shown once and must be acknowledged before the journal opens. */}
      <Stack.Protected guard={mustSaveCode}>
        <Stack.Screen name="recovery-code" options={{ gestureEnabled: false }} />
      </Stack.Protected>
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="sign-in" />
        <Stack.Screen name="register" />
        <Stack.Screen name="recover" />
        <Stack.Screen name="server" />
      </Stack.Protected>
    </Stack>
  );
}
