import {useWidgets} from './WidgetProvider';
import {useI18n} from '@/i18n/I18nProvider';
import {AppText} from './AppText';
import {Button} from './Button';
import {Card} from './Card';
import {Notice} from './Notice';
import {colors} from '@/theme/tokens';
export function WidgetSettings(){const state=useWidgets(),{language}=useI18n(),he=language==='he';return <Card>
 <AppText variant="label" accessibilityRole="header">{he?'וידג׳ט למסך הבית':'Home-screen widget'}</AppText>
 <AppText variant="caption" color={colors.muted}>{he?'היום: קלוריות, חלבון ומים. ללא פרטי חשבון. פתחו את האפליקציה לרענון; המערכת קובעת מתי הווידג׳ט מתעדכן.':'Today’s calories, protein and water, without account details. Open the app to refresh; the system controls when the widget updates.'}</AppText>
 <AppText variant="caption" color={colors.muted}>{he?'נתונים ישנים או חסרים מוסתרים. לאחר הפעלה, הוסיפו את BiteFlow מגלריית הווידג׳טים במסך הבית. בדקו את הגדרות הפרטיות במכשיר.':'Old or unavailable data is hidden. After enabling, add BiteFlow from your home-screen widget gallery. Review your device privacy settings.'}</AppText>
 {!state.available?<Notice tone="info" message={he?'וידג׳טים אינם זמינים בגרסה זו.':'Widgets are unavailable in this build.'}/>:<><Button compact kind="secondary" label={state.enabled?(he?'הסתרת נתונים בווידג׳ט':'Hide widget data'):(he?'הצגת נתונים בווידג׳ט':'Show widget data')} onPress={()=>void state.setEnabled(!state.enabled)}/>{state.enabled?<Button compact kind="ghost" label={he?'רענון':'Refresh'} onPress={()=>void state.refresh()}/>:null}</>}
 {state.error?<Notice tone="warning" message={he?'לא ניתן לעדכן או לנקות את הווידג׳ט. נסו שוב; תצוגת המערכת עשויה להתעכב.':'Could not update or clear the widget. Retry; the system’s displayed copy may update later.'}/>:null}
 </Card>;}
