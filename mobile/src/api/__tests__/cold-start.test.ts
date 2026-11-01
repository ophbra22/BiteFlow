import { createApiClient } from '../client';
import { translate, stripDirectionMarks } from '@/i18n/translate';

// Server readiness survives aborted connections; no actual network traffic.
function sleepingServer(wakeMs = 60_000) {
  const readyAt = Date.now() + wakeMs;
  const calls: RequestInit[] = [];
  const transport = (async (_url: unknown, init: RequestInit) => {
    calls.push(init);
    return new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(new Response('{"awake":true}')), Math.max(0, readyAt - Date.now()));
      init.signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(new Error('aborted'));
      }, { once: true });
    });
  }) as typeof fetch;
  const state = { token: 'account-a' };
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => state.token,
    onSessionRejected: jest.fn(), fetch: transport });
  return { client, calls, state };
}
beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test('GET recovers from a 60 second cold wake and clears waking status', async () => {
  const { client, calls } = sleepingServer();
  const onServerWaking = jest.fn();
  const result = client.request('/health', { onServerWaking }).catch(error => error);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(onServerWaking).toHaveBeenLastCalledWith(true);
  await jest.advanceTimersByTimeAsync(50_000);
  expect(await result).toEqual({ awake: true });
  expect(calls).toHaveLength(2);
  expect(onServerWaking).toHaveBeenLastCalledWith(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each(['POST', 'PUT', 'PATCH', 'DELETE'] as const)('%s timeout sends exactly once with the original key', async method => {
  const { client, calls } = sleepingServer();
  const result = client.request('/write', { method, idempotencyKey: 'stable-key', json: { value: 1 } }).catch(error => error);
  await jest.advanceTimersByTimeAsync(120_000);
  expect(await result).toMatchObject({ kind: 'timeout', outcomeUnknown: true });
  expect(calls).toHaveLength(1);
  expect(calls[0].headers).toMatchObject({ 'Idempotency-Key': 'stable-key' });
});

test('a server that never wakes exhausts three attempts and clears status', async () => {
  const { client, calls } = sleepingServer(200_000);
  const onServerWaking = jest.fn();
  const result = client.request('/health', { onServerWaking }).catch(error => error);
  await jest.advanceTimersByTimeAsync(100_000);
  expect(await result).toMatchObject({ kind: 'timeout' });
  expect(calls).toHaveLength(3);
  expect(onServerWaking).toHaveBeenLastCalledWith(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each(['cancel', 'account'] as const)('%s change during backoff prevents retry', async change => {
  const { client, calls, state } = sleepingServer();
  const controller = new AbortController();
  const result = client.request('/health', { signal: controller.signal }).catch(error => error);
  await jest.advanceTimersByTimeAsync(30_000);
  if (change === 'cancel') controller.abort(); else state.token = 'account-b';
  await jest.advanceTimersByTimeAsync(70_000);
  expect(await result).toMatchObject({ kind: change === 'cancel' ? 'cancelled' : 'unauthorized' });
  expect(calls).toHaveLength(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('waking copy is available in both supported languages', () => {
  expect(stripDirectionMarks(translate('en', 'errors.serverWaking'))).toMatch(/server may be waking/i);
  expect(stripDirectionMarks(translate('he', 'errors.serverWaking'))).toMatch(/השרת/);
});
