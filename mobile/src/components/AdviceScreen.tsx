import {useState,useRef,useEffect,useLayoutEffect} from 'react';
import {ApiError} from '@/api/errors';
import {resumeDraftPath} from '@/domain/drafts';
import {router,useLocalSearchParams} from 'expo-router';
import {useAdvice} from '@/data/useAdvice';
import {useDraft} from '@/data/DraftProvider';
import {useAuth} from '@/auth/AuthProvider';
import {recommendationDraft,type Feature,type RecommendationChoice} from '@/domain/advice';
import {addDays,isIsoDay,todayIso} from '@/domain/dates';
import {periodDates} from '@/domain/trends';
import {useI18n} from '@/i18n/I18nProvider';
import {adviceText} from '@/i18n/advice';
import {errorMessageKey} from '@/api/messages';
import {AdvicePanel} from './AdvicePanel';
import {Screen} from './Screen';
import {Header} from './Header';
import {AppText} from './AppText';
import {Button} from './Button';
import {Notice} from './Notice';
import {Chip} from './Chip';
import {IconButton} from './IconButton';
import {directional} from './Icon';
import {View} from 'react-native';
export function AdviceScreen({feature}:{feature:Feature}){
 const {day}=useLocalSearchParams<{day?:string}>(),{language,t}=useI18n(),a=(k:string)=>adviceText(language,k);
 const [anchor,setAnchor]=useState(isIsoDay(day)?day:todayIso()),[error,setError]=useState<unknown>(null),[selecting,setSelecting]=useState(false);
 const date=feature==='insight'?periodDates(anchor,'week').from:anchor,state=useAdvice(feature,date),{start,newKey,draft,saving}=useDraft(),{api}=useAuth();
 const current=useRef({draft,saving}),busy=useRef(false),alive=useRef(true);
 useLayoutEffect(()=>{current.current={draft,saving};},[draft,saving]);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 const select=async(choice:RecommendationChoice)=>{
  if(!state.fresh||state.loading||busy.current||!state.data||current.current.draft!==null||current.current.saving)return;
  busy.current=true;setSelecting(true);setError(null);const assertSession=api.captureSession(),revision=state.data.revision;
  try{
   assertSession();const authoritative=await api.advice('recommendation',date,language);assertSession();
   if(!alive.current)return;
   if(authoritative.revision!==revision||!('choices' in authoritative)){await state.refresh();throw new ApiError('conflict');}
   const selected=authoritative.choices.find(c=>c.entry.kind===choice.entry.kind&&c.entry.id===choice.entry.id);
   if(!selected){await state.refresh();throw new ApiError('conflict');}
   if(current.current.draft!==null||current.current.saving)return;
   await start(recommendationDraft(selected,newKey()));assertSession();if(alive.current)router.push('/add/review');
  }catch(e){if(alive.current)setError(e);}finally{busy.current=false;if(alive.current)setSelecting(false);}
 };
 return <Screen header={<Header title={a(feature)} leading="back"/>}>
  {feature==='insight'?<View style={{flexDirection:'row',alignItems:'center',gap:8}}>
   <IconButton icon={directional.back} label={a('previous')} onPress={()=>setAnchor(addDays(date,-7))}/>
   <AppText variant="label" ltr center style={{flex:1}}>{date} – {addDays(date,6)}</AppText>
   <IconButton icon={directional.forward} label={a('next')} onPress={()=>setAnchor(addDays(date,7))}/>
  </View>:<><AppText variant="label" ltr>{date}</AppText><View style={{flexDirection:'row'}}><Chip icon="sliders" label={a('preferences')} onPress={()=>router.push('/food-restrictions')}/></View></>}
  {state.enabled===false?<Notice message={a('unavailable')}/>:null}
  {state.error||error?<Notice tone="error" message={t(errorMessageKey(state.error??error))}/>:null}
  {!state.fresh&&state.data?<Notice tone="warning" message={a('stale')}/>:null}
  <Button compact kind="ghost" icon="refresh-cw" label={a('retry')} disabled={state.loading} onPress={()=>{void state.refresh();}}/>
  {feature==='recommendation'&&draft?<Notice message={a('existingDraft')}><Button label={a('resumeDraft')} disabled={saving||selecting} onPress={()=>router.push(resumeDraftPath(draft))}/></Notice>:null}
  {state.data?<AdvicePanel data={state.data} selectable={state.fresh&&!state.loading&&!selecting&&draft===null&&!saving} onSelect={choice=>{void select(choice);}}/>:null}
  {state.wording&&state.data?<><Notice message={a('wordingNotice')}/><Button kind="secondary" label={a('wording')} disabled={!state.fresh||state.loading} onPress={()=>{void state.enhance(newKey());}}/></>:null}
  {state.data&&['unavailable','quota','disabled'].includes(state.data.ai_status)?<Notice message={a('fallback')}/>:null}
 </Screen>;
}
