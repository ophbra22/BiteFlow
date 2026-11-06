import { createApiClient, getServerWakingSnapshot } from '../client';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test('a received HTTP 408 is final, not a transport timeout to retry', async () => {
  const transport = jest.fn(async () => new Response('{}', { status: 408 }));
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'alice',
    onSessionRejected: jest.fn(), fetch: transport });
  const result = client.request('/health').catch(error => error);
  await jest.advanceTimersByTimeAsync(150_000);
  expect(await result).toMatchObject({ kind: 'timeout', status: 408 });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test.each([
  [401, 'unauthorized'], [408, 'timeout'], [429, 'rateLimited'], [503, 'unavailable'],
] as const)('HTTP %i keeps its status when the optional error body stalls', async (status, kind) => {
  const rejected = jest.fn();
  const transport = jest.fn(async (_url: unknown, init: RequestInit) => ({
    ok: false, status, headers: new Headers({ 'Retry-After': '60' }),
    json: () => new Promise((_resolve, reject) => {
      init.signal!.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }),
  } as Response));
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'alice',
    onSessionRejected: rejected, fetch: transport as typeof fetch });
  const result = client.request('/health').catch(error => error);
  await jest.advanceTimersByTimeAsync(150_000);
  expect(await result).toMatchObject({ kind, status, detail: null, retryAfterSeconds: 60 });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(rejected.mock.calls).toEqual(status === 401 ? [['alice']] : []);
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each(['account', 'base'] as const)('%s change during a delayed success discards old data', async change => {
  let token = 'alice', base = 'https://fake.test';
  const readyAt = Date.now() + 115_000;
  const rejected = jest.fn();
  const transport = jest.fn(async (_url: unknown, init: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(new Response('{"owner":"alice"}')), readyAt - Date.now());
    init.signal!.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('aborted')); }, { once: true });
  }));
  const client = createApiClient({ baseUrl: () => base, token: () => token,
    onSessionRejected: rejected, fetch: transport as typeof fetch });
  const result = client.request('/private').catch(error => error);
  await jest.advanceTimersByTimeAsync(110_000);
  if (change === 'account') token = 'bob'; else base = 'https://other.test';
  await jest.advanceTimersByTimeAsync(40_000);
  expect(await result).toMatchObject({ kind: 'unauthorized' });
  expect(transport).toHaveBeenCalledTimes(4);
  expect(rejected).not.toHaveBeenCalled();
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});

test.each(['account', 'base'] as const)('%s change during body parsing discards an explicit-timeout GET result', async change => {
  let token = 'alice', base = 'https://fake.test';
  const client = createApiClient({ baseUrl: () => base, token: () => token, onSessionRejected: jest.fn(),
    fetch: (async () => ({ ok: true, status: 200,
      json: () => new Promise(resolve => setTimeout(() => resolve({ owner: 'alice' }), 100)),
    } as Response)) as typeof fetch });
  const result = client.request('/private', { timeoutMs: 1000 }).catch(error => error);
  await jest.advanceTimersByTimeAsync(50);
  if (change === 'account') token = 'bob'; else base = 'https://other.test';
  await jest.advanceTimersByTimeAsync(50);
  expect(await result).toMatchObject({ kind: 'unauthorized' });
  expect(jest.getTimerCount()).toBe(0);
});

test.each([204, 401])('stale HTTP %i cannot return success or reject the current session', async status => {
  let token = 'alice';
  const rejected = jest.fn();
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => token,
    onSessionRejected: rejected, fetch: (async () => new Promise<Response>(resolve => {
      setTimeout(() => resolve(new Response(null, { status })), 100);
    })) as typeof fetch });
  const result = client.request('/private').catch(error => error);
  await jest.advanceTimersByTimeAsync(50);
  token = 'bob';
  await jest.advanceTimersByTimeAsync(50);
  expect(await result).toMatchObject({ kind: 'unauthorized' });
  expect(rejected).not.toHaveBeenCalled();
  expect(jest.getTimerCount()).toBe(0);
});

test('public GET ignores token changes while still bound to its server', async () => {
  let token = 'alice';
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => token,
    onSessionRejected: jest.fn(), fetch: (async () => new Promise<Response>(resolve => {
      setTimeout(() => resolve(new Response('{"public":true}')), 100);
    })) as typeof fetch });
  const result = client.request('/public', { auth: false });
  token = 'bob';
  await jest.advanceTimersByTimeAsync(100);
  expect(await result).toEqual({ public: true });
  expect(jest.getTimerCount()).toBe(0);
});

test.each([401, 429])('caller cancellation while reading HTTP %i details remains cancellation', async status => {
  const rejected = jest.fn();
  const transport = jest.fn(async (_url: unknown, init: RequestInit) => ({
    ok: false, status, headers: new Headers(),
    json: () => new Promise((_resolve, reject) => {
      init.signal!.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }),
  } as Response));
  const client = createApiClient({ baseUrl: () => 'https://fake.test', token: () => 'alice',
    onSessionRejected: rejected, fetch: transport as typeof fetch });
  const controller = new AbortController();
  const result = client.request('/health', { signal: controller.signal }).catch(error => error);
  await jest.advanceTimersByTimeAsync(10_000);
  controller.abort();
  expect(await result).toMatchObject({ kind: 'cancelled' });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(rejected).not.toHaveBeenCalled();
  expect(getServerWakingSnapshot()).toBe(false);
  expect(jest.getTimerCount()).toBe(0);
});
