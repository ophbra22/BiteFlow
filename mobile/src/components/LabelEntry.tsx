import {useEffect,useRef,useState} from 'react';
import {router} from 'expo-router';
import * as Picker from 'expo-image-picker';
import {useAuth} from '@/auth/AuthProvider';
import {useDraft} from '@/data/DraftProvider';
import {getAddIntent} from '@/data/add-intent';
import {prepareUpload} from '@/data/images';
import {manualDraft,productDraft} from '@/domain/drafts';
import {labelDraft,type LabelResult} from '@/domain/label-input';
import {useI18n} from '@/i18n/I18nProvider';
import {colors} from '@/theme/tokens';
import {Screen} from './Screen';import {Header} from './Header';import {TextField} from './TextField';import {Button} from './Button';import {Notice} from './Notice';import {AppText} from './AppText';
export function LabelEntry(){const {user}=useAuth();return <LabelForm key={user?.id}/>;}
function LabelForm(){
 const {api}=useAuth(),{draft,start,newKey}=useDraft(),{t,language}=useI18n();
 const [busy,setBusy]=useState(false),[failed,setFailed]=useState(false),[ocr,setOcr]=useState(false),[barcode,setBarcode]=useState(''),[fallback,setFallback]=useState<LabelResult|null>(null);
 const generation=useRef(0),abort=useRef<AbortController|null>(null),locked=useRef(false);
 const text=draft?.origin==='label'?draft.inputText??'':'';
 useEffect(()=>{let live=true;api.capabilities().then(c=>{if(live)setOcr(c.label_ocr===true&&process.env.EXPO_PUBLIC_LABEL_OCR_ENABLED==='1');}).catch(()=>{});const g=generation,a=abort;return()=>{live=false;g.current++;a.current?.abort();};},[api]);
 const change=(value:string)=>{generation.current++;setFailed(false);setFallback(null);void start({...manualDraft(newKey(),getAddIntent()),origin:'label',inputText:value});};
 const openReview=async(result:LabelResult,guard:()=>void,n:number)=>{guard();if(n!==generation.current)return;await start(labelDraft(newKey(),result,getAddIntent()));guard();if(n===generation.current)router.replace('/add/review');};
 const accept=async(result:LabelResult,guard:()=>void,n:number)=>{
  guard();if(n!==generation.current)return;
  if(result.product.barcode){
   let product;
   try{product=await api.product(result.product.barcode);}
   catch{guard();if(n===generation.current)setFallback(result);return;}
   guard();if(n!==generation.current)return;
   await openReview({...result,product,warnings:[]},guard,n);
  }else await openReview(result,guard,n);
 };
 const useFallback=async()=>{
  if(locked.current||!fallback)return;locked.current=true;setBusy(true);setFailed(false);
  const n=++generation.current,guard=api.captureSession();
  try{await openReview({...fallback,warnings:[...fallback.warnings,'exact_barcode_unavailable']},guard,n);}
  catch{if(n===generation.current)setFailed(true);}
  finally{locked.current=false;if(n===generation.current)setBusy(false);}
 };

 const run=async(camera?:boolean)=>{
  if(locked.current)return;locked.current=true;setBusy(true);setFailed(false);setFallback(null);const n=++generation.current,guard=api.captureSession(),controller=new AbortController();abort.current=controller;
  let upload:Awaited<ReturnType<typeof prepareUpload>>|undefined;
  try {
   if(camera===undefined){await accept(await api.parseLabel(text,barcode),guard,n);return;}
   if(camera){const permission=await Picker.requestCameraPermissionsAsync();guard();if(!permission.granted)throw new Error('permission');}
   const picked=await (camera?Picker.launchCameraAsync:Picker.launchImageLibraryAsync)({mediaTypes:['images'],allowsEditing:true,quality:1,exif:false});
   guard();if(n!==generation.current||picked.canceled)return;
   upload=await prepareUpload(picked.assets[0],true);guard();if(n!==generation.current)return;
   await accept(await api.extractLabel(upload,language,newKey(),controller.signal),guard,n);
  }catch{if(n===generation.current)setFailed(true);}finally{upload?.dispose();locked.current=false;if(n===generation.current)setBusy(false);}
 };
 const exact=async()=>{if(locked.current)return;locked.current=true;setBusy(true);setFailed(false);setFallback(null);const n=++generation.current,guard=api.captureSession();try{const product=await api.product(barcode);guard();if(n!==generation.current)return;await start(productDraft(newKey(),product,getAddIntent()));guard();if(n===generation.current)router.replace('/add/review');}catch{if(n===generation.current)setFailed(true);}finally{locked.current=false;if(n===generation.current)setBusy(false);}};
 return <Screen header={<Header title={t('label.title')}/>}>
  <AppText color={colors.muted}>{t('label.hint')}</AppText>
  <TextField label={t('label.barcode')} value={barcode} onChangeText={value=>{setBarcode(value);setFallback(null);}} keyboardType="number-pad" maxLength={14} ltr editable={!busy}/>
  <Button compact kind="secondary" icon="search" label={t('label.exact')} disabled={busy||!barcode} onPress={exact}/>
  <TextField testID="label-text" label={t('label.text')} value={text} onChangeText={change} multiline maxLength={8000} editable={!busy} hint={t('label.example')}/>
  <Button testID="label-parse" label={t('label.review')} disabled={busy||!text.trim()} onPress={()=>run()}/>
  {ocr?<><Notice message={t('label.privacy')}/><Button compact testID="label-camera" kind="secondary" icon="camera" label={t('add.camera')} disabled={busy} onPress={()=>run(true)}/><Button compact kind="secondary" icon="image" label={t('add.library')} disabled={busy} onPress={()=>run(false)}/></>:<Notice message={t('label.off')}/>}
  {fallback?<><Notice tone="warning" message={t('label.exactUnavailable')}/><Button testID="label-fallback" label={t('label.useTranscription')} disabled={busy} onPress={useFallback}/></>:null}
  {failed?<Notice tone="error" message={t('label.failed')}/>:null}
  {busy?<Button kind="secondary" label={t('common.cancel')} onPress={()=>{generation.current++;abort.current?.abort();locked.current=false;setBusy(false);}}/>:null}
 </Screen>;
}
