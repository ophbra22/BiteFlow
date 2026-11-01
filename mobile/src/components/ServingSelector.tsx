import {useEffect,useRef,useState} from 'react';
import {View} from 'react-native';
import type {ReviewFood} from '@/domain/meal-analysis';
import {applyServing,type ServingConversion} from '@/domain/servings';
import type {TKey} from '@/i18n/translate';
import {useI18n} from '@/i18n/I18nProvider';
import {Button} from './Button';
import {TextField} from './TextField';
import {AppText} from './AppText';
import {Notice} from './Notice';
export type ServingLoader=(id:string,version:string)=>Promise<{conversions:ServingConversion[]}>;
type Props={food:ReviewFood;onChange:(f:ReviewFood)=>void;disabled:boolean;load:ServingLoader};
export function ServingSelector(props:Props){return <Selector key={`${props.food.reference?.id}:${props.food.reference?.source_version}:${props.food.basis??'g'}`} {...props}/>;}
function Selector({food,onChange,disabled,load}:Props) {
 const {t}=useI18n(),[rows,setRows]=useState<ServingConversion[]|null>(null),[selected,setSelected]=useState<ServingConversion|null>(null),[quantity,setQuantity]=useState('1'),[busy,setBusy]=useState(false),[error,setError]=useState(false),generation=useRef(0);
 const id=food.reference?.id,version=food.reference?.source_version;
 useEffect(()=>{const g=generation;return()=>{g.current++;};},[]);
 if(!id||!version) return null;
 const find=async()=>{const n=++generation.current;setBusy(true);setError(false);try{const r=await load(id,version);if(n===generation.current)setRows(r.conversions.filter(c=>c.food_id===id&&c.source_version===version&&c.basis===(food.basis??'g')));}catch{if(n===generation.current)setError(true);}finally{if(n===generation.current)setBusy(false);}};
 const original=food.originalPortion;
 const unit=(value:string)=>t((['cup','tablespoon','teaspoon','slice','piece','half','small','medium','large','serving'].includes(value)?`servings.units.${value}`:'servings.units.other') as TKey);
 const confidence=(value:string)=>t(value==='source_reported'?'servings.confidence.source_reported':value==='derived'?'servings.confidence.derived':'servings.confidence.unknown');
 return <View style={{gap:8}}>
  <Button compact label={t('servings.title')} icon="coffee" kind="secondary" disabled={disabled||busy} onPress={find}/>
  {rows?.length===0||error?<Notice message={t('servings.missing')}/>:null}
  {rows?.map(r=><Button compact key={r.id} label={t('servings.option',{unit:unit(r.unit),source:r.label,amount:r.amount,basis:t(`units.${r.basis}`)})} kind="ghost" disabled={disabled} onPress={()=>{setSelected(r);setError(false);}}/>)}
  {selected?<><AppText variant="caption">{confidence(selected.confidence)}</AppText><TextField label={t('servings.count')} value={quantity} onChangeText={setQuantity} editable={!disabled} maxLength={12} keyboardType="decimal-pad"/>
   <Button compact kind="secondary" label={t('servings.apply')} disabled={disabled} onPress={()=>{try{onChange(applyServing(food,selected,quantity));setError(false);}catch{setError(true);}}}/></>:null}
  {original?.food_specific_conversion_id?<AppText variant="caption">{`${original.quantity} × ${original.unit} → ${food.amount} ${t(`units.${food.basis??'g'}`)}`}</AppText>:null}
 </View>;
}
