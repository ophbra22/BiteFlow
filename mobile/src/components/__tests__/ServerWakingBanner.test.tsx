import { act, render } from '@testing-library/react-native';
import * as SplashScreen from 'expo-splash-screen';
import { createApiClient } from '@/api/client';
import { I18nProvider } from '@/i18n/I18nProvider';
import { ServerWakingBanner } from '../ServerWakingBanner';

jest.mock('react-native-safe-area-context', () => jest.requireActual('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-splash-screen', () => ({ hideAsync: jest.fn(() => Promise.resolve()) }));

function server(wakeMs: number) {
  const readyAt = Date.now() + wakeMs;
  return createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'synthetic-session',
    onSessionRejected: jest.fn(), fetch: (async (_url, init) => new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(new Response('{}')), Math.max(0, readyAt - Date.now()));
      init?.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('aborted')); }, { once: true });
    })) as typeof fetch });
}
const advance = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });
beforeEach(() => { jest.useFakeTimers(); jest.clearAllMocks(); });
afterEach(() => jest.useRealTimers());

test.each([
  { language: 'en', copy: /The server may be waking up/, direction: 'ltr', align: 'left' },
  { language: 'he', copy: /ייתכן שהשרת מתעורר/, direction: 'rtl', align: 'right' },
] as const)('a real client request shows and clears the $language banner', async ({ language, copy, direction, align }) => {
  const view = await render(<I18nProvider initial={language}><ServerWakingBanner /></I18nProvider>);
  const request = server(60_000).request('/health');
  expect(view.queryByText(copy)).toBeNull();
  await advance(10_000);
  expect(view.getByText(copy)).toHaveStyle({ writingDirection: direction, textAlign: align });
  expect(view.getByRole('status')).toHaveProp('accessibilityLiveRegion', 'polite');
  expect(SplashScreen.hideAsync).toHaveBeenCalled();
  await advance(50_000);
  await expect(request).resolves.toEqual({});
  expect(view.queryByText(copy)).toBeNull();
});

test('overlapping slow requests keep the banner until the final request settles', async () => {
  const view = await render(<I18nProvider initial="en"><ServerWakingBanner /></I18nProvider>);
  const first = server(60_000).request('/first');
  const second = server(75_000).request('/second');
  await advance(10_000);
  expect(view.getByRole('status')).toBeTruthy();
  await advance(50_000);
  await first;
  expect(view.getByRole('status')).toBeTruthy();
  await advance(15_000);
  await second;
  expect(view.queryByRole('status')).toBeNull();
});

test.each(['cancel', 'timeout'] as const)('%s clears the visible status', async outcome => {
  const view = await render(<I18nProvider initial="en"><ServerWakingBanner /></I18nProvider>);
  const controller = new AbortController();
  const result = server(200_000).request('/slow', { signal: controller.signal }).catch(error => error);
  await advance(10_000);
  expect(view.getByRole('status')).toBeTruthy();
  if (outcome === 'cancel') await act(async () => controller.abort());
  else await advance(90_000);
  expect(await result).toMatchObject({ kind: outcome === 'cancel' ? 'cancelled' : 'timeout' });
  expect(view.queryByRole('status')).toBeNull();
});

test('mounting during an existing wake shows current status; a mutation never shows it', async () => {
  const request = server(60_000).request('/health');
  await advance(10_000);
  const view = await render(<I18nProvider initial="en"><ServerWakingBanner /></I18nProvider>);
  expect(view.getByRole('status')).toBeTruthy();
  await advance(50_000);
  await request;
  const write = server(60_000).request('/write', { method: 'POST', idempotencyKey: 'stable' }).catch(error => error);
  await advance(10_000);
  expect(view.queryByRole('status')).toBeNull();
  await advance(20_000);
  expect(await write).toMatchObject({ kind: 'timeout' });
  expect(view.queryByRole('status')).toBeNull();
});