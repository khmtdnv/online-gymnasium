import type { z } from 'zod';
import type { SessionManager } from '../../features/auth/session';
import {
  ApiError,
  ApiNetworkError,
  ApiProtocolError,
  responseError,
  SessionChangedError,
} from './errors';

export interface ApiClient {
  json<T>(path: string, options: RequestInit, schema: z.ZodType<T>): Promise<T>;
  pdf(path: string, signal?: AbortSignal): Promise<Blob>;
  downloadHomeworkFile(
    path: string,
    expected: { size_bytes: number; content_type: string },
    signal?: AbortSignal,
  ): Promise<Blob>;
}

/** Единственная точка авторизованных запросов; запись повторяется только после auth-401. */
export function createApiClient({
  fetchImpl,
  session,
}: {
  fetchImpl: typeof fetch;
  session: Pick<SessionManager, 'getAccessToken' | 'getEpoch' | 'refresh' | 'invalidate'>;
}): ApiClient {
  function checkPath(path: string) {
    const url = new URL(path, 'https://og.invalid');
    if (
      !path.startsWith('/api/v1/') ||
      path.includes('\\') ||
      url.origin !== 'https://og.invalid' ||
      !url.pathname.startsWith('/api/v1/')
    )
      throw new ApiProtocolError();
  }
  function assertEpoch(expected: number) {
    if (session.getEpoch() !== expected) throw new SessionChangedError();
  }
  async function request(
    path: string,
    options: RequestInit,
  ): Promise<{ response: Response; epoch: number }> {
    checkPath(path);
    const epoch = session.getEpoch();
    let usedToken = session.getAccessToken();
    if (!usedToken) throw new ApiError(401, 'authentication_error', 'Not authenticated');
    async function send(): Promise<Response> {
      assertEpoch(epoch);
      const headers = new Headers(options.headers);
      headers.set('Authorization', `Bearer ${usedToken}`);
      if (
        options.body !== undefined &&
        !(options.body instanceof FormData) &&
        !headers.has('Content-Type')
      )
        headers.set('Content-Type', 'application/json');
      let response: Response;
      try {
        response = await fetchImpl(path, {
          ...options,
          headers,
          credentials: 'same-origin',
          cache: 'no-store',
          redirect: 'error',
        });
      } catch (error) {
        assertEpoch(epoch);
        if (error instanceof Error && error.name === 'AbortError') throw error;
        throw new ApiNetworkError();
      }
      assertEpoch(epoch);
      return response;
    }
    let response = await send();
    if (response.status === 401) {
      // Другой параллельный запрос мог уже заменить токен, пока этот ответ шёл по сети.
      if (session.getAccessToken() === usedToken) await session.refresh();
      assertEpoch(epoch);
      usedToken = session.getAccessToken();
      if (!usedToken) throw new ApiError(401, 'authentication_error', 'Not authenticated');
      response = await send();
      if (response.status === 401) {
        const error = await responseError(response);
        assertEpoch(epoch);
        session.invalidate();
        throw error;
      }
    }
    if (!response.ok) {
      const error = await responseError(response);
      assertEpoch(epoch);
      throw error;
    }
    return { response, epoch };
  }
  return {
    async json<T>(path: string, options: RequestInit, schema: z.ZodType<T>): Promise<T> {
      const { response, epoch } = await request(path, options);
      const requestId = response.headers.get('X-Request-ID') ?? undefined;
      if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json'))
        throw new ApiProtocolError(requestId);
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        assertEpoch(epoch);
        throw new ApiProtocolError(requestId);
      }
      assertEpoch(epoch);
      const parsed = schema.safeParse(body);
      if (!parsed.success) throw new ApiProtocolError(requestId);
      return parsed.data;
    },
    async pdf(path: string, signal?: AbortSignal): Promise<Blob> {
      const { response, epoch } = await request(path, {
        signal,
        headers: { Accept: 'application/pdf' },
      });
      const requestId = response.headers.get('X-Request-ID') ?? undefined;
      if (
        response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !==
        'application/pdf'
      )
        throw new ApiProtocolError(requestId);
      const blob = await response.blob();
      assertEpoch(epoch);
      if ((await blob.slice(0, 5).text()) !== '%PDF-') throw new ApiProtocolError(requestId);
      assertEpoch(epoch);
      return blob;
    },
    async downloadHomeworkFile(path, expected, signal) {
      const { response, epoch } = await request(path, { signal });
      const requestId = response.headers.get('X-Request-ID') ?? undefined;
      if (
        response.headers.get('Content-Type')?.split(';')[0].trim() !== expected.content_type ||
        Number(response.headers.get('Content-Length')) !== expected.size_bytes ||
        expected.size_bytes < 1 ||
        expected.size_bytes > 10485760
      )
        throw new ApiProtocolError(requestId);
      const reader = response.body?.getReader();
      if (!reader) throw new ApiProtocolError(requestId);
      const chunks: BlobPart[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          assertEpoch(epoch);
          signal?.throwIfAborted();
          if (done) break;
          size += value.byteLength;
          if (size > expected.size_bytes) throw new ApiProtocolError(requestId);
          chunks.push(value);
        }
        if (size !== expected.size_bytes) throw new ApiProtocolError(requestId);
        return new Blob(chunks, { type: expected.content_type });
      } finally {
        try {
          await reader.cancel();
        } finally {
          reader.releaseLock();
        }
      }
    },
  };
}
