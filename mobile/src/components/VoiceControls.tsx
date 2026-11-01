import {useEffect, useRef, useState} from 'react';
import {AppState} from 'react-native';

import {useI18n} from '@/i18n/I18nProvider';
import {loadSpeechBridge, SpeechSession, type SpeechState} from '@/native/speech';
import {AppText} from './AppText';
import {Button} from './Button';
import {Chip} from './Chip';
import {colors} from '@/theme/tokens';
import {Notice} from './Notice';
import type {VoiceSlotProps} from './TextEntry';

/** Recognition only supplies editable text. Nutrition and saving use TextEntry's shared flow. */
export function VoiceControls({onTranscript, onRecordingChange, disabled}: VoiceSlotProps) {
  const {t, language} = useI18n();
  const [locale, setLocale] = useState<'he-IL' | 'en-US'>(language === 'he' ? 'he-IL' : 'en-US');
  const [state, setState] = useState<SpeechState>('idle');
  const [ready, setReady] = useState(false);
  const session = useRef<SpeechSession | null>(null);
  const callbacks = useRef({onTranscript, onRecordingChange});
  useEffect(() => { callbacks.current = {onTranscript, onRecordingChange}; }, [onTranscript, onRecordingChange]);
  useEffect(() => {
    let active = true;
    void loadSpeechBridge().then(bridge => {
      if (!active) return;
      if (!bridge) { setState('unavailable'); return; }
      session.current = new SpeechSession(bridge, next => {
        setState(next);
        callbacks.current.onRecordingChange(['checking', 'listening', 'stopping'].includes(next));
      }, text => callbacks.current.onTranscript(text));
      setReady(true);
    });
    const subscription = AppState.addEventListener('change', next => session.current?.appState(next));
    return () => {
      active = false;
      subscription.remove();
      session.current?.dispose();
      session.current = null;
    };
  }, []);
  const recording = ['checking', 'listening', 'stopping'].includes(state);
  const fallback = state === 'denied' || state === 'unavailable' || state === 'error';
  return <>
    <AppText variant="caption" color={colors.muted}>{t('voice.privacy')}</AppText>
    <Chip icon="globe" disabled={recording || disabled} label={t(locale === 'he-IL' ? 'voice.hebrew' : 'voice.english')}
      onPress={() => setLocale(value => value === 'he-IL' ? 'en-US' : 'he-IL')}/>
    {fallback ? <Notice tone="warning" message={t(`voice.${state}`)}><AppText testID="voice-fallback">{t('voice.typeInstead')}</AppText></Notice> : null}
    <AppText variant="bodyStrong" center accessibilityLiveRegion="polite">{t(state === 'checking' || state === 'listening' || state === 'stopping' ? `voice.${state}` : 'voice.ready')}</AppText>
    {recording ? <>
      <Button testID="voice-stop" label={t('voice.stop')} disabled={state === 'stopping'} onPress={() => session.current?.stop()}/>
      <Button compact testID="voice-cancel" kind="ghost" label={t('common.cancel')} onPress={() => session.current?.cancel()}/>
    </> : <Button testID="voice-start" icon="mic" label={t('voice.start')} disabled={!ready || disabled} onPress={() => { void session.current?.start(locale); }}/>}
  </>;
}
