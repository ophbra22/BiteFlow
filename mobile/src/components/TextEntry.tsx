import {useEffect,useRef,useState,type ComponentType} from 'react';
import {router} from 'expo-router';
import {useAuth} from '@/auth/AuthProvider';
import {isApiError} from '@/api/errors';
import {useDraft} from '@/data/DraftProvider';
import {getAddIntent} from '@/data/add-intent';
import {manualDraft} from '@/domain/drafts';
import {textDraft} from '@/domain/text-input';
import {useI18n} from '@/i18n/I18nProvider';
import {Screen} from './Screen';
import {Header} from './Header';
import {TextField} from './TextField';
import {Button} from './Button';
import {Notice} from './Notice';
import {AppText} from './AppText';
import {Chip} from './Chip';
import {colors} from '@/theme/tokens';

export type VoiceSlotProps={onTranscript:(value:string)=>void;onRecordingChange:(active:boolean)=>void;disabled?:boolean};
type Props={mode:'text'|'voice';VoiceSlot?:ComponentType<VoiceSlotProps>};
export function TextEntry(props:Props){const {user}=useAuth();return <TextForm key={user?.id??'signed-out'} {...props}/>;}
function TextForm({mode,VoiceSlot}:Props){
 const {api}=useAuth(),{draft,start,newKey}=useDraft(),{t,language}=useI18n();
 const [busy,setBusy]=useState(false),[failure,setFailure]=useState(false),[allowAi,setAllowAi]=useState(false);
 const [recording,setRecording]=useState(false);
 const generation=useRef(0),abort=useRef<AbortController|null>(null);
 const input=draft?.origin===mode?draft.inputText??'':'';
 useEffect(()=>{const active=generation,controller=abort;return()=>{active.current++;controller.current?.abort();};},[]);
 const change=(value:string)=>{generation.current++;abort.current?.abort();setBusy(false);setFailure(false);void start({...manualDraft(newKey(),getAddIntent()),origin:mode,inputText:value.slice(0,2000)});};
 const parse=async()=>{
  if(busy||!input.trim()||!draft||recording)return;
  const id=++generation.current,controller=new AbortController();abort.current=controller;setBusy(true);setFailure(false);
  try{
   const assertSession=api.captureSession();
   const result=await api.analyzeText({text:input,language,local_date:draft.day,meal_category:draft.mealType,input_method:mode,allow_ai:allowAi},draft.key,controller.signal);
   assertSession();if(id!==generation.current)return;
   await start(textDraft(result,newKey(),mode,input,{day:draft.day,mealType:draft.mealType}));
   assertSession();if(id===generation.current)router.replace('/add/review');
  }catch(error){if(id===generation.current&&(!isApiError(error)||error.kind!=='cancelled'))setFailure(true);}
  finally{if(id===generation.current)setBusy(false);}
 };
 return <Screen header={<Header title={t(mode==='voice'?'text.voiceTitle':'text.title')}/>}>
  <AppText color={colors.muted}>{t('text.hint')}</AppText>
  {VoiceSlot?<VoiceSlot disabled={busy} onTranscript={change} onRecordingChange={setRecording}/>:null}
  <TextField testID="food-description" label={t('text.description')} value={input} onChangeText={change} maxLength={2000} multiline editable={!busy&&!recording}/>
  <Chip toggle selected={allowAi} icon="zap" label={t(allowAi?'text.aiOn':'text.aiOff')} disabled={busy||recording} onPress={()=>setAllowAi(v=>!v)}/>
  {allowAi?<AppText variant="caption" color={colors.muted}>{t('text.aiPrivacy')}</AppText>:null}
  {failure?<Notice tone="error" message={t('text.failed')}/>:null}
  {busy?<Button kind="secondary" label={t('common.cancel')} onPress={()=>{generation.current++;abort.current?.abort();setBusy(false);}}/>:<Button testID="parse-text" label={t('text.review')} disabled={!input.trim()||recording} onPress={parse}/>}
  <Button compact kind="ghost" label={t('add.manual')} onPress={async()=>{generation.current++;abort.current?.abort();await start(manualDraft(newKey(),getAddIntent()));router.replace('/add/review');}}/>
 </Screen>;
}
