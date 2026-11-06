import { createApiClient, getServerWakingSnapshot } from '../client';
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
  const state = { token: 'account-a', base: 'https://fake.test' };
  const client = createApiClient({ baseUrl: () => state.base, token: () => state.token,
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

test('a server that never wakes stops at the overall deadline and clears status', async () => {
  const { client, calls } = sleepingServer(200_000);
  const onServerWaking = jest.fn();
  let settled = false;
  const result = client.request('/health', { onServerWaking }).catch(error => error).finally(() => { settled = true; });
  await jest.advanceTimersByTimeAsync(149_999);
  expect(settled).toBe(false);
  expect(getServerWakingSnapshot()).toBe(true);
  await jest.advanceTimersByTimeAsync(1);
  expect(await result).toMatchObject({ kind: 'timeout' });
  expect(calls).toHaveLength(5);
  expect(calls.every(call => call.signal?.aborted)).toBe(true);
  expect(onServerWaking).toHaveBeenLastCalledWith(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each([115_000, 149_999])('GET recovers when server wakes after %i ms', async wakeMs => {
  const { client, calls } = sleepingServer(wakeMs);
  const result = client.request('/health').catch(error => error);
  await jest.advanceTimersByTimeAsync(wakeMs);
  expect(await result).toEqual({ awake: true });
  expect(calls.length).toBeLessThanOrEqual(5);
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each([110_000, 123_500])('caller cancellation at %i ms stops active fetch or backoff', async cancelAt => {
  const { client, calls } = sleepingServer(200_000);
  const controller = new AbortController();
  const result = client.request('/health', { signal: controller.signal }).catch(error => error);
  await jest.advanceTimersByTimeAsync(cancelAt);
  controller.abort();
  expect(await result).toMatchObject({ kind: 'cancelled' });
  const dispatched = calls.length;
  await jest.advanceTimersByTimeAsync(200_000);
  expect(calls).toHaveLength(dispatched);
  expect(calls.every(call => call.signal?.aborted)).toBe(true);
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each([400, 401, 403, 404, 429, 500, 503])('HTTP %i never retries', async status => {
  const transport = jest.fn(async () => new Response('{}', { status }));
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'account-a',
    onSessionRejected: jest.fn(), fetch: transport as typeof fetch });
  await expect(client.request('/health')).rejects.toMatchObject({ status });
  await jest.advanceTimersByTimeAsync(200_000);
  expect(transport).toHaveBeenCalledTimes(1);
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test('explicit GET timeout retains a single attempt', async () => {
  const { client, calls } = sleepingServer(115_000);
  const result = client.request('/health', { timeoutMs: 45_000 }).catch(error => error);
  await jest.advanceTimersByTimeAsync(150_000);
  expect(await result).toMatchObject({ kind: 'timeout' });
  expect(calls).toHaveLength(1);
  expect(jest.getTimerCount()).toBe(0);
});

test.each(['account', 'base'] as const)('%s change during late backoff prevents another dispatch', async change => {
  const { client, calls, state } = sleepingServer(200_000);
  const result = client.request('/health').catch(error => error);
  await jest.advanceTimersByTimeAsync(123_500);
  if (change === 'account') state.token = 'account-b'; else state.base = 'https://other.test';
  await jest.advanceTimersByTimeAsync(500);
  expect(await result).toMatchObject({ kind: 'unauthorized' });
  expect(calls).toHaveLength(4);
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test('network rejection is final and never retries', async () => {
  const transport = jest.fn(async () => { throw new Error('offline'); });
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'account-a',
    onSessionRejected: jest.fn(), fetch: transport });
  await expect(client.request('/health')).rejects.toMatchObject({ kind: 'network' });
  await jest.advanceTimersByTimeAsync(200_000);
  expect(transport).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('a stalled successful response body times out without repeating a received response', async () => {
  const signals: AbortSignal[] = [];
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'account-a',
    onSessionRejected: jest.fn(), fetch: (async (_url, init) => {
      const signal = init!.signal!;
      signals.push(signal);
      return { ok: true, status: 200, json: () => new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      }) } as Response;
    }) as typeof fetch });
  const result = client.request('/health').catch(error => error);
  await jest.advanceTimersByTimeAsync(150_000);
  expect(await result).toMatchObject({ kind: 'timeout' });
  expect(signals).toHaveLength(1);
  expect(signals.every(signal => signal.aborted)).toBe(true);
  expect(getServerWakingSnapshot()).toBe(false);
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
