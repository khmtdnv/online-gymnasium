import { z } from 'zod';
import { currentUserSchema, tokenResponseSchema } from '../../lib/api/contracts';
import { ApiNetworkError, ApiProtocolError, responseError } from '../../lib/api/errors';

/** Auth транспорт не обновляет токен рекурсивно и никогда не повторяет POST. */
export function createAuthApi(fetchImpl: typeof fetch) {
  async function request(path: string, options: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await fetchImpl(`/api/v1/auth/${path}`, {
        ...options,
        credentials: 'same-origin',
        cache: 'no-store',
        redirect: 'error',
      });
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new ApiNetworkError();
    }
    if (!response.ok) throw await responseError(response);
    return response;
  }
  async function json<T>(path: string, options: RequestInit, schema: z.ZodType<T>): Promise<T> {
    const response = await request(path, options);
    if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json'))
      throw new ApiProtocolError(response.headers.get('X-Request-ID') ?? undefined);
    try {
      return schema.parse(await response.json());
    } catch {
      throw new ApiProtocolError(response.headers.get('X-Request-ID') ?? undefined);
    }
  }
  return {
    login: (email: string, password: string) =>
      json(
        'login',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        },
        tokenResponseSchema,
      ),
    refresh: () => json('refresh', { method: 'POST' }, tokenResponseSchema),
    me: (accessToken: string) =>
      json('me', { headers: { Authorization: `Bearer ${accessToken}` } }, currentUserSchema),
    logout: async () => {
      const response = await request('logout', { method: 'POST' });
      if (response.status !== 204)
        throw new ApiProtocolError(response.headers.get('X-Request-ID') ?? undefined);
    },
  };
}
