/**
 * HTTP access to the FoodLogger backend.
 *
 * The app signs in as a native client: the server returns an opaque session token
 * (no cookie), the app keeps it in the device keystore and sends it as a bearer
 * credential. Cookies are switched off so nothing ambient is ever attached.
 */
import { ApiError, kindForStatus } from './errors';

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  json?: unknown;
  form?: FormData;
  /** Attach the session token. Defaults to true. */
  auth?: boolean;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  /** An explicit timeout opts out of automatic cold-start retries. */
  timeoutMs?: number;
  /** Per-request hint: show errors.serverWaking while true; cleared on settlement. */
  onServerWaking?: (waking: boolean) => void;
  signal?: AbortSignal;
  responseType?: 'json' | 'text';
};

export type ClientDeps = {
  baseUrl: () => string;
  token: () => string | null;
  /** Called when the server rejects the session token that was sent. */
  onSessionRejected: (token: string) => void;
  fetch?: typeof fetch;
};

export const DEFAULT_TIMEOUT_MS = 30_000;
export const UPLOAD_TIMEOUT_MS = 60_000;

export type ApiClient = ReturnType<typeof createApiClient>;

export function createApiClient(deps: ClientDeps) {
  const doFetch = deps.fetch ?? fetch;

  async function requestOnce<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const base = deps.baseUrl();
    if (!base) throw new ApiError('config');
    const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
    const sentToken = options.auth === false ? null : deps.token();
    if (options.auth !== false) {
      if (!sentToken) throw new ApiError('unauthorized', { status: 401 });
      headers.Authorization = `Bearer ${sentToken}`;
    }
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
    let body: BodyInit | undefined;
    if (options.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.json);
    } else if (options.form) {
      // The platform sets the multipart boundary itself.
      body = options.form;
    }

    const controller = new AbortController();
    if (options.signal?.aborted) throw new ApiError('cancelled');
    const cancel = () => controller.abort();
    options.signal?.addEventListener('abort', cancel);
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

    try {
      let response: Response;
      try {
        response = await doFetch(base + path, {
          method: options.method ?? 'GET', headers, body, credentials: 'omit', signal: controller.signal,
        });
      } catch {
        throw new ApiError(options.signal?.aborted ? 'cancelled' : timedOut ? 'timeout' : 'network');
      }
      const checkAbort = () => {
        if(options.signal?.aborted || timedOut) throw new ApiError(options.signal?.aborted ? 'cancelled' : 'timeout');
      };
      checkAbort();
      if (!response.ok) {
        let detail: string | null = null;
        try {
          const payload = await response.json();
          if (payload && typeof payload.detail === 'string') detail = payload.detail;
        } catch { checkAbort(); }
        checkAbort();
        if (response.status === 401 && sentToken) deps.onSessionRejected(sentToken);
        const retryAfter = Number(response.headers.get('Retry-After'));
        throw new ApiError(kindForStatus(response.status), {status:response.status,detail,
          retryAfterSeconds:Number.isFinite(retryAfter) && retryAfter>0 ? retryAfter : null});
      }
      if(response.status===204) return null as T;
      try {
        const result=options.responseType==='text' ? await response.text() : await response.json();
        checkAbort();
        return result as T;
      } catch {
        checkAbort();
        throw new ApiError('server',{status:response.status});
      }
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', cancel);
    }
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    // Only default-deadline, bodyless GETs may be repeated. Writes retain one
    // attempt, their original idempotency key and unknown-outcome semantics.
    const canRetry = (options.method ?? 'GET') === 'GET' &&
      options.json === undefined && options.form === undefined && options.timeoutMs === undefined;
    if (!canRetry) return requestOnce<T>(path, options);
    const base = deps.baseUrl();
    const token = options.auth === false ? null : deps.token();
    let waking = false;
    const notify = (value: boolean) => {
      waking = value;
      // UI observers must not turn a successful request into a failed one.
      try { options.onServerWaking?.(value); } catch { /* observer only */ }
    };
    const wakingTimer = setTimeout(() => notify(true), 10_000);
    try {
      for (let attempt = 0; ; attempt++) {
        if (options.signal?.aborted) throw new ApiError('cancelled');
        if (deps.baseUrl() !== base || (options.auth !== false && deps.token() !== token)) {
          throw new ApiError('unauthorized', { status: 401 });
        }
        try {
          return await requestOnce<T>(path, options);
        } catch (error) {
          // A timeout is a possible sleeping server, not proof of one. Other
          // errors (including rate limits and rejected sessions) remain final.
          if (!(error instanceof ApiError) || error.kind !== 'timeout' || attempt === 2) throw error;
          await new Promise<void>((resolve, reject) => {
            const finish = () => { options.signal?.removeEventListener('abort', cancel); resolve(); };
            const timer = setTimeout(finish, 1_000);
            const cancel = () => {
              clearTimeout(timer);
              options.signal?.removeEventListener('abort', cancel);
              reject(new ApiError('cancelled'));
            };
            options.signal?.addEventListener('abort', cancel);
            if (options.signal?.aborted) cancel();
          });
        }
      }
    } finally {
      clearTimeout(wakingTimer);
      if (waking) notify(false);
    }
  }
  // Capture before any local asynchronous work; never dispatch an old account's
  // photo or draft using a newly signed-in account's credentials.
  const captureSession = () => {
    const token = deps.token();
    const base = deps.baseUrl();
    return () => {
      if (!token || deps.token() !== token || deps.baseUrl() !== base) {
        throw new ApiError('unauthorized', { status: 401 });
      }
    };
  };
  return { request, captureSession };
}
