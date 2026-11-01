import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { ActivityIndicator, Linking, StyleSheet, View } from 'react-native';

import { isApiError } from '@/api/errors';
import { errorMessageKey } from '@/api/messages';
import { useAuth } from '@/auth/AuthProvider';
import { AppText } from '@/components/AppText';
import { Button } from '@/components/Button';
import { Chip } from '@/components/Chip';
import { Disclosure } from '@/components/Disclosure';
import { Header } from '@/components/Header';
import { IconButton } from '@/components/IconButton';
import { Notice } from '@/components/Notice';
import { Screen } from '@/components/Screen';
import { TextField } from '@/components/TextField';
import { useDraft } from '@/data/DraftProvider';
import { getAddIntent } from '@/data/add-intent';
import { prepareUpload } from '@/data/images';
import { manualDraft, productDraft } from '@/domain/drafts';
import { validateBarcode } from '@/domain/validation';
import { useI18n } from '@/i18n/I18nProvider';
import { ltr } from '@/i18n/format';
import type { TKey } from '@/i18n/translate';
import { haptics } from '@/native/haptics';
import { colors, radius, spacing } from '@/theme/tokens';

type Status =
  | { name: 'idle' }
  | { name: 'looking'; barcode: string }
  | { name: 'reading' }
  | { name: 'notFound'; barcode: string }
  | { name: 'unavailable'; barcode: string }
  | { name: 'error'; message: TKey };

/** Find a packaged product: scan with the camera, type the digits, or read a photo of the barcode. */
export default function BarcodeLookup() {
  const { t } = useI18n();
  const { api } = useAuth();
  const { start, newKey } = useDraft();
  const [permission, requestPermission] = useCameraPermissions();
  const [status, setStatus] = useState<Status>({ name: 'idle' });
  const [digits, setDigits] = useState('');
  const [digitsError, setDigitsError] = useState<TKey | null>(null);
  const [torch, setTorch] = useState(false);
  const [cameraFailed, setCameraFailed] = useState(false);
  const busy = useRef(false);

  const lookUp = async (barcode: string) => {
    if (busy.current) return;
    busy.current = true;
    setStatus({ name: 'looking', barcode });
    try {
      const product = await api.product(barcode);
      await start(productDraft(newKey(), product, getAddIntent()));
      haptics.success();
      router.replace('/add/review');
    } catch (error) {
      haptics.warning();
      if (isApiError(error) && error.kind === 'notFound') setStatus({ name: 'notFound', barcode });
      else if (isApiError(error) && error.kind === 'unavailable') setStatus({ name: 'unavailable', barcode });
      else setStatus({ name: 'error', message: errorMessageKey(error, 'product') });
    } finally {
      busy.current = false;
    }
  };

  const onScanned = ({ data }: { data: string }) => {
    // The camera reports the same code many times a second; act on the first valid one.
    if (busy.current || status.name !== 'idle') return;
    const code = data.trim();
    if (validateBarcode(code) === null) void lookUp(code);
  };

  const submitDigits = () => {
    const code = digits.replace(/\s+/g, '');
    const problem = validateBarcode(code);
    setDigitsError(problem);
    if (!problem) void lookUp(code);
  };

  const fromPhoto = async () => {
    if (busy.current) return;
    try {
      const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 1 });
      if (picked.canceled || !picked.assets?.length) return;
      setStatus({ name: 'reading' });
      const upload = await prepareUpload(picked.assets[0]);
      const { barcode } = await api.scanBarcode(upload);
      await lookUp(barcode);
    } catch (error) {
      setStatus({
        name: 'error',
        message: isApiError(error) ? errorMessageKey(error, 'barcodePhoto') : 'barcode.noBarcodeInPhoto',
      });
    }
  };

  const enterManually = async () => {
    await start(manualDraft(newKey(), getAddIntent()));
    router.replace('/add/review');
  };

  const working = status.name === 'looking' || status.name === 'reading';
  const canScan = !!permission?.granted && !cameraFailed;
  const workingText =
    status.name === 'looking' ? t('barcode.lookingUp', { barcode: ltr(status.barcode) }) : t('barcode.readingPhoto');

  const manualEntry = (
    <>
      <TextField
        testID="barcode-digits"
        label={t('barcode.digitsLabel')}
        hint={t('barcode.digitsHint')}
        value={digits}
        onChangeText={(text) => {
          setDigits(text.replace(/[^\d\s]/g, ''));
          setDigitsError(null);
        }}
        error={digitsError ? t(digitsError) : null}
        ltr
        keyboardType="number-pad"
        inputMode="numeric"
        maxLength={18}
        returnKeyType="search"
        onSubmitEditing={submitDigits}
        editable={!working}
      />
      <Button
        testID="barcode-lookup"
        kind="secondary"
        icon="search"
        label={t('barcode.lookUp')}
        onPress={submitDigits}
        disabled={working}
      />
    </>
  );

  return (
    <Screen header={<Header title={t('barcode.title')} />}>
      {canScan ? (
        <View style={styles.camera}>
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            enableTorch={torch}
            active={status.name === 'idle'}
            barcodeScannerSettings={{ barcodeTypes: ['ean13', 'ean8', 'upc_a', 'upc_e'] }}
            onBarcodeScanned={status.name === 'idle' ? onScanned : undefined}
            onMountError={() => setCameraFailed(true)}
            accessibilityLabel={t('a11y.scanner')}
          />
          <View style={styles.frame} pointerEvents="none">
            <View style={[styles.corner, styles.topStart]} />
            <View style={[styles.corner, styles.topEnd]} />
            <View style={[styles.corner, styles.bottomStart]} />
            <View style={[styles.corner, styles.bottomEnd]} />
          </View>
          {status.name === 'idle' ? (
            <View style={styles.aim} pointerEvents="none">
              <AppText variant="label" center>
                {t('barcode.aim')}
              </AppText>
            </View>
          ) : null}
          <View style={styles.torch}>
            <IconButton
              icon={torch ? 'zap-off' : 'zap'}
              label={torch ? t('barcode.torchOff') : t('barcode.torchOn')}
              filled
              onPress={() => setTorch((value) => !value)}
            />
          </View>
          {working ? (
            <View style={styles.progress} accessibilityLiveRegion="polite">
              <ActivityIndicator size="large" color={colors.sand} />
              <AppText center variant="bodyStrong">
                {workingText}
              </AppText>
            </View>
          ) : null}
        </View>
      ) : null}

      {!permission ? (
        <View style={styles.pending} accessibilityLabel={t('common.loading')}>
          <ActivityIndicator color={colors.sand} />
        </View>
      ) : null}
      {permission && !permission.granted && permission.canAskAgain ? (
        <Notice icon="camera" title={t('permissions.cameraTitle')} message={t('permissions.cameraBody')}>
          <Button testID="allow-camera" label={t('permissions.allow')} onPress={requestPermission} />
        </Notice>
      ) : null}
      {permission && !permission.granted && !permission.canAskAgain ? (
        <Notice tone="warning" icon="camera-off" message={t('permissions.cameraDenied')}>
          <Button compact kind="secondary" label={t('permissions.openSettings')} onPress={() => Linking.openSettings()} />
        </Notice>
      ) : null}
      {cameraFailed ? <Notice tone="warning" icon="camera-off" message={t('barcode.simulatorNote')} /> : null}

      {working && !canScan ? (
        <View style={styles.pending} accessibilityLiveRegion="polite">
          <ActivityIndicator color={colors.sand} />
          <AppText center>{workingText}</AppText>
        </View>
      ) : null}

      {status.name === 'notFound' ? (
        <Notice
          tone="warning"
          title={t('barcode.notFoundTitle')}
          message={t('barcode.notFoundBody', { barcode: ltr(status.barcode) })}>
          <Button testID="enter-manually" label={t('barcode.enterManually')} onPress={enterManually} />
          <Button compact kind="ghost" label={t('barcode.scanAgain')} onPress={() => setStatus({ name: 'idle' })} />
        </Notice>
      ) : null}
      {status.name === 'unavailable' ? (
        <Notice tone="error" title={t('barcode.unavailableTitle')} message={t('barcode.unavailableBody')}>
          <Button kind="secondary" label={t('common.retry')} onPress={() => lookUp(status.barcode)} />
          <Button compact kind="ghost" label={t('barcode.enterManually')} onPress={enterManually} />
        </Notice>
      ) : null}
      {status.name === 'error' ? (
        <Notice tone="error" message={t(status.message)}>
          <Button compact kind="secondary" label={t('barcode.scanAgain')} onPress={() => setStatus({ name: 'idle' })} />
        </Notice>
      ) : null}

      {/* With a working camera the typed fallback stays out of the way; without one it is the main path. */}
      {canScan ? (
        <Disclosure key="scanner" label={t('barcode.enterDigits')}>
          {manualEntry}
        </Disclosure>
      ) : (
        <View key="typed" style={styles.manual}>
          {manualEntry}
        </View>
      )}
      <View style={styles.chips}>
        <Chip icon="image" label={t('barcode.fromPhoto')} onPress={fromPhoto} disabled={working} />
      </View>
    </Screen>
  );
}

const CORNER = 28;
const STROKE = 3;

const styles = StyleSheet.create({
  camera: {
    width: '100%',
    aspectRatio: 1,
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  frame: { width: '78%', height: '40%' },
  corner: { position: 'absolute', width: CORNER, height: CORNER, borderColor: colors.sand },
  topStart: { top: 0, left: 0, borderTopWidth: STROKE, borderLeftWidth: STROKE, borderTopLeftRadius: radius.sm },
  topEnd: { top: 0, right: 0, borderTopWidth: STROKE, borderRightWidth: STROKE, borderTopRightRadius: radius.sm },
  bottomStart: { bottom: 0, left: 0, borderBottomWidth: STROKE, borderLeftWidth: STROKE, borderBottomLeftRadius: radius.sm },
  bottomEnd: { bottom: 0, right: 0, borderBottomWidth: STROKE, borderRightWidth: STROKE, borderBottomRightRadius: radius.sm },
  aim: {
    position: 'absolute',
    top: spacing.lg,
    left: spacing.lg,
    right: spacing.lg,
    alignItems: 'center',
  },
  torch: { position: 'absolute', bottom: spacing.sm, right: spacing.sm },
  progress: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    padding: spacing.lg,
    backgroundColor: colors.scrim,
  },
  pending: { gap: spacing.md, alignItems: 'center', paddingVertical: spacing.lg },
  manual: { gap: spacing.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
