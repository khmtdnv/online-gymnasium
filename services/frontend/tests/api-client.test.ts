import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { createApiClient } from '../app/lib/api/client';
import { ApiError, ApiProtocolError, SessionChangedError } from '../app/lib/api/errors';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'r-123' },
  });
const schema = z.object({ value: z.string() });

function setup(fetchImpl: typeof fetch) {
  let accessToken = 'old';
  const session = {
    getAccessToken: () => accessToken,
    getEpoch: vi.fn(() => 1),
    refresh: vi.fn(async () => {
      accessToken = 'replacement';
      return accessToken;
    }),
    invalidate: vi.fn(),
  };
  return { client: createApiClient({ fetchImpl, session }), session };
}

describe('API transport', () => {
  it('обновляет токен один раз и повторяет запрос с новым Bearer', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(json({ value: 'ok' }));
    const { client, session } = setup(fetchImpl);
    expect(await client.json('/api/v1/example', {}, schema)).toEqual({ value: 'ok' });
    expect(session.refresh).toHaveBeenCalledOnce();
    expect(new Headers(fetchImpl.mock.calls[1][1]?.headers).get('Authorization')).toBe(
      'Bearer replacement',
    );
  });

  it('прекращает цикл после второго 401', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => json({}, 401));
    const { client, session } = setup(fetchImpl);
    await expect(client.json('/api/v1/example', {}, schema)).rejects.toBeInstanceOf(ApiError);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(session.refresh).toHaveBeenCalledOnce();
    expect(session.invalidate).toHaveBeenCalledOnce();
  });

  it.each([403, 502, 504])('не запускает refresh при %i', async (status) => {
    const { client, session } = setup(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          json(
            { error: { code: 'upstream_error', message: 'Request failed', request_id: 'r-123' } },
            status,
          ),
        ),
    );
    await expect(client.json('/api/v1/example', {}, schema)).rejects.toMatchObject({
      status,
      requestId: 'r-123',
    });
    expect(session.refresh).not.toHaveBeenCalled();
  });

  it('не превращает неверный JSON-контракт в пустой успешный результат', async () => {
    const { client } = setup(vi.fn<typeof fetch>().mockResolvedValue(json({ wrong: true })));
    await expect(client.json('/api/v1/example', {}, schema)).rejects.toBeInstanceOf(
      ApiProtocolError,
    );
  });

  it('не повторяет POST после потери соединения', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('connection lost'));
    const { client } = setup(fetchImpl);
    await expect(
      client.json('/api/v1/documents/certificates', { method: 'POST', body: '{}' }, schema),
    ).rejects.toThrow();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it('не возвращает ответ старого аккаунта после смены epoch', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(json({ value: 'private' }));
    const { client, session } = setup(fetchImpl);
    session.getEpoch.mockReturnValueOnce(1).mockReturnValue(2);
    await expect(client.json('/api/v1/example', {}, schema)).rejects.toBeInstanceOf(
      SessionChangedError,
    );
  });

  it('не отправляет токен на произвольный внешний URL', async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const { client } = setup(fetchImpl);
    await expect(client.json('https://evil.test/api', {}, schema)).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('отклоняет HTML вместо PDF до передачи blob в компонент', async () => {
    const { client } = setup(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response('<html>Error</html>', { headers: { 'Content-Type': 'text/html' } }),
        ),
    );
    await expect(client.pdf('/api/v1/documents/job/content')).rejects.toBeInstanceOf(
      ApiProtocolError,
    );
  });

  it('запоздалый второй 401 не очищает уже новую сессию', async () => {
    let finish!: (body: unknown) => void;
    const body = new Promise<unknown>((resolve) => {
      finish = resolve;
    });
    const rejected = json({}, 401);
    const readBody = vi.spyOn(rejected, 'json').mockReturnValue(body);
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(rejected);
    const { client, session } = setup(fetchImpl);
    const request = client.json('/api/v1/example', {}, schema);
    await vi.waitFor(() => expect(readBody).toHaveBeenCalledOnce());
    session.getEpoch.mockReturnValue(2);
    const assertion = expect(request).rejects.toBeInstanceOf(SessionChangedError);
    finish({ error: { code: 'authentication_error', message: 'Expired', request_id: 'late' } });
    await assertion;
    expect(session.invalidate).not.toHaveBeenCalled();
  });
});
