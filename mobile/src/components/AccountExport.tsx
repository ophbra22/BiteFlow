import {useRef,useState} from 'react';
import {Platform} from 'react-native';
import {useAuth} from '@/auth/AuthProvider';
import {useI18n} from '@/i18n/I18nProvider';
import {accountExportDisabled,buildAccountArchive,sharePrivateExport} from '@/storage/export';
import {captureAccountStorage} from '@/storage/kv';
import {colors} from '@/theme/tokens';
import {AppText} from './AppText';
import {Button} from './Button';
import {Card} from './Card';
import {Notice} from './Notice';

export function AccountExport(){
 const {user,api}=useAuth(),{language}=useI18n(),he=language==='he';
 const [busy,setBusy]=useState(false),[failed,setFailed]=useState(false),running=useRef(false);
 if(accountExportDisabled())return null;
 const exportData=async()=>{
  if(!user||running.current)return;
  running.current=true;setBusy(true);setFailed(false);
  const ownerCheck=captureAccountStorage(user.id),sessionCheck=api.captureSession();
  const check=()=>{ownerCheck();sessionCheck();};
  try{await sharePrivateExport({name:`biteflow-account-${Date.now()}.json`,mime:'application/json',check,load:()=>buildAccountArchive(user.id,api.exportAccount)});}
  catch{setFailed(true);}finally{running.current=false;setBusy(false);}
 };
 return <Card>
  <AppText accessibilityRole="header" variant="label">{he?'ייצוא נתוני החשבון':'Export account data'}</AppText>
  <AppText variant="caption" color={colors.muted}>{he?'הקובץ כולל מידע רגיש: יומן, יעדים, מתכונים, העדפות תזונה, מדידות וטיוטות שנשמרו במכשיר זה. בחרו יעד אחסון מאובטח.':'The file contains sensitive journal, goal, recipe, dietary preference, measurement and saved draft data from this device. Choose a secure destination.'}</AppText>
  <AppText variant="caption" color={colors.muted}>{he?'נתוני השרת והמכשיר נקראים בנפרד. מידע שלא נשמר, מכשירים אחרים וספריית הבריאות החיצונית אינם כלולים. מחיקת חשבון אינה מוחקת עותקים ששיתפתם.':'Server and device data are read separately. Unsaved input, other devices and the external Health library are excluded. Account deletion cannot remove copies you share.'}</AppText>
  {Platform.OS==='web'?<Notice tone="info" message={he?'ייצוא הקובץ זמין באפליקציה ב־iOS וב־Android.':'File export is available in the iOS and Android app.'}/>:<Button compact kind="secondary" icon="download" testID="export-account" label={he?'הכנת קובץ לשיתוף':'Prepare file to share'} onPress={()=>void exportData()} busy={busy}/>}
  {failed?<Notice tone="warning" message={he?'לא ניתן להשלים את הייצוא או לנקות את הקובץ הזמני. התחברו ונסו שוב. אם החשבון גדול מדי, פנו לתמיכה לייצוא מלא.':'Could not complete export or clear its temporary file. Connect and retry. For an oversized account, contact support for a complete export.'}/>:null}
 </Card>;
}
