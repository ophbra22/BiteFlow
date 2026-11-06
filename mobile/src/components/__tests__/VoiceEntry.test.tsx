import AsyncStorage from '@react-native-async-storage/async-storage';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react-native';
import {TextEntry} from '../TextEntry';
import {VoiceControls} from '../VoiceControls';
import {AppState,ScrollView,type AppStateStatus} from 'react-native';
import type {SpeechEvent,SpeechBridge} from '@/native/speech';
import {MealAnalysisReview} from '../MealAnalysisReview';
import {I18nProvider} from '@/i18n/I18nProvider';
import {DraftProvider,useDraft} from '@/data/DraftProvider';
import {JournalStore} from '@/data/journal-store';
import {openAccountStorage} from '@/storage/kv';
import {textResult} from '@/test-fixtures/text-input';
import type {MealDraft} from '@/domain/canonical';
import {ApiError} from '@/api/errors';
// RN exposes ScrollView through a lazy getter. Its Jest mock loads the real
// ScrollView/Animated/Fabric modules to construct the mock; cold Babel transforms
// otherwise consume the first test's 5-second budget during mount. Initialize
// that existing mock during module setup, without rendering or replacing app UI.
void ScrollView;

const saved:MealDraft[]=[];let mockFailure=false;
let mockAppStateChange:(state:AppStateStatus)=>void;const mockRemove=jest.fn();
let mockUserId='alice';let mockAvailable=true,mockGranted=true,mockMissing=false;const mockRequests:unknown[]=[];
const mockListeners=new Map<string,(e:SpeechEvent)=>void>();
const mockBridge:SpeechBridge={available:async()=>mockAvailable,permissions:async()=>({granted:mockGranted,canAskAgain:false}),requestPermission:async()=>({granted:mockGranted,canAskAgain:false}),
 start:jest.fn(()=>mockListeners.get('start')?.({})),stop:jest.fn(()=>mockListeners.get('end')?.({})),abort:jest.fn(),
 listen:(name,callback)=>{mockListeners.set(name,callback);return()=>{mockListeners.delete(name);};}};
jest.mock('@/native/speech',()=>({...jest.requireActual('@/native/speech'),loadSpeechBridge:async()=>mockMissing?null:mockBridge}));
const mockApi={captureSession:()=>()=>{},capabilities:async()=>({canonical_writes:true,partial_core_writes:true,tiny_portion_writes:true}),
 analyzeText:async(body:unknown)=>{mockRequests.push(body);if(mockFailure)throw new ApiError('network');return textResult();},nutritionReferences:async()=>({foods:[]}),
 addCanonicalMeal:async(body:MealDraft)=>{saved.push(body);return [{id:'text-saved',day:body.local_date,meal_type:'lunch' as const,name:'rice',emoji:'🍽️',grams:100,food_id:'custom',calories:130,protein:2,carbs:28,fat:0.3,created_at:new Date().toISOString(),details:{}}];},
 day:async(day:string)=>({day,meals:[],summary:{count:0,calories:0,protein:0,carbs:0,fat:0}}),deleteMeal:async()=>null};
let mockJournal:JournalStore;
jest.mock('@/auth/AuthProvider',()=>({useAuth:()=>({user:{id:mockUserId},api:mockApi,journal:mockJournal})}));
jest.mock('expo-router',()=>({router:{replace:jest.fn(),dismissTo:jest.fn(),back:jest.fn()},useNavigation:()=>({canGoBack:()=>true})}));
jest.mock('expo-crypto',()=>({randomUUID:()=> 'text-entry-test-key'}));
function Harness(){const {draft}=useDraft();return draft?.analysis?<MealAnalysisReview/>:<TextEntry mode="voice" VoiceSlot={VoiceControls}/>;}
beforeEach(async()=>{saved.length=0;mockFailure=false;await AsyncStorage.clear();openAccountStorage('alice');mockJournal=new JournalStore('alice',mockApi);});

beforeEach(()=>{mockUserId='alice';mockAvailable=true;mockGranted=true;mockMissing=false;mockListeners.clear();mockRequests.length=0;jest.clearAllMocks();jest.spyOn(AppState,'addEventListener').mockImplementation((_name,callback)=>{mockAppStateChange=callback;return {remove:mockRemove};});});
const mount=()=>render(<I18nProvider initial="he"><DraftProvider><Harness/></DraftProvider></I18nProvider>);
it('retains required Hebrew transcript, allows correction without rerecording, then uses the shared parser and confirmation',async()=>{
 await mount();await fireEvent.press(await screen.findByTestId('voice-start'));
 await waitFor(()=>expect(mockBridge.start).toHaveBeenCalledWith('he-IL'));
 await act(()=>mockListeners.get('result')?.({text:'אכלתי שתי ביצים וחצי פיתה',final:true}));
 await fireEvent.press(screen.getByTestId('voice-stop'));
 expect(screen.getByTestId('food-description').props.value).toBe('אכלתי שתי ביצים וחצי פיתה');
 await fireEvent.changeText(screen.getByTestId('food-description'),'100g rice');
 expect(mockBridge.start).toHaveBeenCalledTimes(1);expect(saved).toHaveLength(0);
 await fireEvent.press(screen.getByTestId('parse-text'));
 expect(mockRequests).toEqual([expect.objectContaining({text:'100g rice',input_method:'voice',allow_ai:false})]);
 expect(await screen.findByTestId('save-analyzed-meal')).toBeTruthy();expect(saved).toHaveLength(0);
 await fireEvent.press(screen.getByTestId('confirm-text-item'));await fireEvent.press(screen.getByTestId('save-analyzed-meal'));
 await waitFor(()=>expect(saved).toHaveLength(1));expect(saved[0].input_method).toBe('voice');
});
it.each(['denied','unavailable','missing'] as const)('%s speech keeps typed input usable and never starts audio',async reason=>{
 mockGranted=reason!=='denied';mockAvailable=reason!=='unavailable';mockMissing=reason==='missing';
 await mount();
 if(!mockMissing)await fireEvent.press(await screen.findByTestId('voice-start'));
 await screen.findByTestId('voice-fallback');
 await fireEvent.changeText(screen.getByTestId('food-description'),'100g rice');await fireEvent.press(screen.getByTestId('parse-text'));
 expect(await screen.findByTestId('save-analyzed-meal')).toBeTruthy();expect(mockBridge.start).not.toHaveBeenCalled();expect(saved).toHaveLength(0);
});
it('background and unmount abort recognition and ignore stale results',async()=>{
 const view=await mount();await fireEvent.press(await screen.findByTestId('voice-start'));
 await waitFor(()=>expect(mockBridge.start).toHaveBeenCalled());const late=mockListeners.get('result');
 await act(()=>mockAppStateChange('background'));await act(()=>late?.({text:'stale background words'}));
 expect(screen.getByTestId('food-description').props.value).toBe('');expect(mockListeners.size).toBe(0);
 await view.unmount();expect(mockRemove).toHaveBeenCalled();expect(mockBridge.abort).toHaveBeenCalled();
});

it('account replacement disposes the old session and ignores its transcript callbacks',async()=>{
 const view=await mount();await fireEvent.press(await screen.findByTestId('voice-start'));
 await waitFor(()=>expect(mockBridge.start).toHaveBeenCalled());const late=mockListeners.get('result');
 mockUserId='bob';openAccountStorage('bob');mockJournal=new JournalStore('bob',mockApi);
 await view.rerender(<I18nProvider initial="he"><DraftProvider><Harness/></DraftProvider></I18nProvider>);
 await act(()=>late?.({text:'Alice private transcript'}));
 expect(screen.getByTestId('food-description').props.value).toBe('');expect(mockBridge.abort).toHaveBeenCalled();expect(saved).toHaveLength(0);
});
