import {useState,useSyncExternalStore} from 'react';
import {useI18n} from '@/i18n/I18nProvider';
import {healthEnabled,isHealthConnect} from '@/native/health/platform';
import {emptyChoices,type Choices} from '@/native/health/types';
import {useHealth} from './HealthProvider';
import {Chip} from './Chip';
import {Screen} from './Screen';import {Header} from './Header';import {Button} from './Button';import {Notice} from './Notice';import {AppText} from './AppText';
export function HealthSettings(){const service=useHealth();return service?<Editor service={service}/>:null;}
function Editor({service}:{service:NonNullable<ReturnType<typeof useHealth>>}){
 const {language}=useI18n(),he=language==='he';
 const state=useSyncExternalStore(service.subscribe,()=>service.state);
 const [selection,setSelection]=useState<{service:typeof service;choices:Choices}|null>(null),[error,setError]=useState(false);
 const choices=selection?.service===service?selection.choices:service.choices?.()??emptyChoices();
 const setChoices=(choices:Choices)=>setSelection({service,choices});
 const action=async(fn:()=>Promise<void>)=>{setError(false);try{await fn();}catch{setError(true);}};
 const labels:Record<keyof Choices,string>={nutrition:he?'כתיבת תזונה':'Write nutrition',water:he?'כתיבת מים':'Write water',weight:he?'ייבוא משקל גוף':'Import body weight',steps:he?'ייבוא דגימות צעדים':'Import step samples'};
 return <Screen header={<Header leading="back" title={isHealthConnect?'Health Connect':he?'בריאות Apple':'Apple Health'}/>}>
  <Notice message={he?'ייבוא משקל וצעדים מעביר את הנתונים שנבחרו ליומן הפרטי בחשבון המחובר. תזונה היא נתון שאישרתם, ולא מדידה מאומתת.':'Importing weight and steps sends the selected data to your signed-in private journal. Nutrition is user-confirmed data, not a verified measurement.'}/>
  <Notice message={he?'תוצאות ריקות אינן מוכיחות הרשאת קריאה. הרשאות חלקיות אינן מונעות רישום רגיל. הסנכרון מתבצע כשהיישום פתוח.':'Empty results do not prove read permission. Partial permissions do not prevent ordinary logging. Sync runs while the app is open.'}/>
  <Notice message={isHealthConnect?(he?'בכל סנכרון נקראים עד 20 עמודים לכל סוג נתון שנבחר. כשנותרות רשומות, לחצו שוב על סנכרון להמשך.':'Each sync reads up to 20 pages per selected type. When records remain, use Sync / retry to continue.'):(he?'ייבוא Apple Health מוגבל לעד 1,000 דגימות לכל סוג נתון שנבחר ב־30 הימים האחרונים. אם הגבול נחצה, הייבוא נעצר עם שגיאה; אין המשך בעמוד נוסף.':'Apple Health imports at most 1,000 samples per selected type in the last 30 days. Above this limit, the import stops with an error; further pages are not supported.')}/>
  <Notice message={he?'היסטוריית הסנכרון מוגבלת ל־10,000 רשומות בבעלות האפליקציה, כולל מחיקות שממתינות לטיפול. חריגה עוצרת את הסנכרון עם שגיאה; אין למחוק נתוני סנכרון כדי לעקוף אותה.':'Sync history is limited to 10,000 owned records, including pending deletions. Exceeding it stops sync with an error; do not erase sync data to bypass it.'}/>
  {!healthEnabled?<Notice message={he?'החיבור מושבת בגרסה זו.':'Health integration is disabled in this build.'}/>:null}
  {isHealthConnect?<>
   <Notice message={he?'אזור הזמן ביומן נבחר במועד הייבוא הראשון. ההיסט המקורי של המקור נשמר בנפרד; אין למקור שם אזור זמן.':'The journal display timezone is chosen at first import. Original source offsets are retained separately; Health Connect does not provide an IANA timezone.'}/>
   <AppText>{state.availability==='install_required'?(he?'נדרשת התקנה או עדכון של Health Connect':'Health Connect install or update required'):state.available?(he?'Health Connect זמין':'Health Connect available'):(he?'Health Connect אינו זמין':'Health Connect unavailable')}</AppText>
   <Button label={he?'התקנה / ניהול הרשאות Health Connect':'Install / manage Health Connect permissions'} disabled={!healthEnabled||state.busy} onPress={()=>{void action(()=>service.manage());}}/>
   {(['weight','steps'] as const).map(k=><AppText key={k}>{labels[k]+': '+(state.readGranted?.[k]?(he?'הרשאה ניתנה':'permission granted'):(he?'לא ניתנה הרשאה או בוטלה':'not granted or revoked'))}</AppText>)}
   {state.recovered?<Notice message={he?'תוקף אסימון השינויים פג. נקראו מחדש 30 ימים; ייתכן שמחיקות ישנות לא נקלטו. יש לבדוק את ההיסטוריה.':'A changes token expired. The last 30 days were read again; older deletions may be missing. Review your imported history.'}/>:null}
   {state.more?<Notice message={he?'קיימות רשומות נוספות. לחצו על סנכרון להמשך.':'More records remain. Use Sync / retry to continue.'}/>:null}
  </>:null}
  <AppText>{state.connected?(he?'מחובר':'Connected'):(he?'מנותק':'Disconnected')}</AppText>
  {(Object.keys(labels) as (keyof Choices)[]).map(k=><Chip toggle selected={choices[k]} key={k} disabled={!healthEnabled||state.busy} label={labels[k]+': '+(choices[k]?(he?'פעיל':'on'):(he?'כבוי':'off'))} onPress={()=>setChoices({...choices,[k]:!choices[k]})}/>)}
  <Button label={he?'חיבור הנתונים שנבחרו':'Connect selected data'} disabled={!healthEnabled||state.busy||!Object.values(choices).some(Boolean)} onPress={()=>{void action(async()=>{await service.connect(choices);await service.sync();});}}/>
  <Button compact kind="secondary" icon="refresh-cw" label={he?'סנכרון וניסיון חוזר':'Sync / retry'} disabled={!healthEnabled||!state.connected||state.busy} onPress={()=>{void action(()=>service.sync());}}/>
  <Button compact kind="ghost" label={he?'ניתוק':'Disconnect'} disabled={!state.connected} onPress={()=>{void action(()=>service.disconnect());}}/>
  {state.exportFailed?<Notice message={(he?'ייצואים שעדיין ממתינים: ':'Exports still pending: ')+state.exportFailed}/>:null}
  {state.repair?<Notice message={he?'מחיקות מסוימות לא אושרו. הן נשארו ממתינות; יש לבדוק ולתקן ב-Health Connect. נתונים אחרים יכולים להסתנכרן.':'Some deletions are unacknowledged and remain pending. Review and repair in Health Connect; other data can continue syncing.'}/>:null}
  {state.busy?<Notice message={he?'מסנכרן…':'Syncing…'}/>:null}
  {error||state.error?<Notice message={he?'הסנכרון לא הושלם. אפשר לנסות שוב; היומן נשמר.':'Sync did not finish. Retry is safe; your journal is retained.'}/>:null}
  <AppText>{(he?'רשומות חסומות לפי הרשאה: ':'Records blocked by permission: ')+state.blocked}</AppText>
  <AppText>{(he?'רשומות ללא זמן מקורי תקין: ':'Records withheld without a valid original timestamp: ')+state.withheld}</AppText>
  <Notice message={he?'הניתוק עוצר סנכרון אך אינו מוחק דגימות שכבר נכתבו. אפשר לנהל הרשאות ונתונים ביישום בריאות. ייבוא מוגבל ל־30 הימים האחרונים; דגימות צעדים אינן סכום יומי מנוכה כפילויות.':'Disconnect stops sync and retains existing Health samples. Manage permissions and data in the Health app. Imports cover the last 30 days; raw step samples are not a deduplicated daily total.'}/>
  <Notice message={he?'להלן תצוגה מקדימה של עד 10 רשומות מהייבוא האחרון. זו אינה רשימת כל הדגימות שיובאו.':'Below is a preview of up to 10 records from the latest import, not a list of all imported samples.'}/>
  {(state.imports??[]).slice(-10).map(s=><AppText key={s.external_id}>{`${s.kind}: ${s.value} ${s.kind==='weight'?'kg':''} · ${s.start} · ${s.source_bundle}`}</AppText>)}
 </Screen>;
}
