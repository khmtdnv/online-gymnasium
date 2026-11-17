import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import {
  createSessionManager,
  type CookieLocks,
  type SessionChannel,
} from '../app/features/auth/session';

const user = {
  id: '6c6f3434-e4cc-4619-8c2a-8d733913ecda',
  email: 'admin@school.ru',
  role: 'admin',
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const token = () => json({ access_token: 'access-token' });

class SharedLocks implements CookieLocks {
  private tail: Promise<unknown> = Promise.resolve();
  request<T>(_name: string, operation: () => Promise<T>): Promise<T> {
    const result = this.tail.then(operation);
    this.tail = result.catch(() => undefined);
    return result;
  }
}

function setup(
  fetchImpl: typeof fetch,
  locks: CookieLocks | null = new SharedLocks(),
  channel: SessionChannel | null = null,
) {
  const queryClient = new QueryClient();
  const clear = vi.spyOn(queryClient, 'clear');
  return {
    session: createSessionManager({ fetchImpl, queryClient, locks, channel }),
    clear,
    queryClient,
  };
}

function channels(): [SessionChannel, SessionChannel] {
  const listeners = [
    new Set<(event: MessageEvent) => void>(),
    new Set<(event: MessageEvent) => void>(),
  ];
  return [0, 1].map((index) => ({
    postMessage: (data: unknown) => {
      queueMicrotask(() =>
        listeners[1 - index].forEach((listener) => listener(new MessageEvent('message', { data }))),
      );
    },
    addEventListener: (_type: 'message', listener: (event: MessageEvent) => void) => {
      listeners[index].add(listener);
    },
    removeEventListener: (_type: 'message', listener: (event: MessageEvent) => void) => {
      listeners[index].delete(listener);
    },
  })) as [SessionChannel, SessionChannel];
}

describe('сессия', () => {
  it('запоздалые уведомления чужого login не отменяют ожидающий logout', async () => {
    const listeners = new Set<(event: MessageEvent) => void>();
    const channel: SessionChannel = {
      postMessage: vi.fn(),
      addEventListener: (_, listener) => {
        listeners.add(listener);
      },
      removeEventListener: (_, listener) => {
        listeners.delete(listener);
      },
    };
    let cookie = true;
    const fetchImpl = vi.fn<typeof fetch>(async (path) => {
      if (path === '/api/v1/auth/logout') {
        cookie = false;
        return new Response(null, { status: 204 });
      }
      if (path === '/api/v1/auth/me') return json(user);
      return cookie ? token() : json({}, 401);
    });
    const locks = new SharedLocks();
    const { session } = setup(fetchImpl, locks, channel);
    await session.bootstrap();
    let release!: () => void;
    const blocker = locks.request(
      'og-auth-cookie',
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    await vi.waitFor(() => expect(release).toBeDefined());
    const leaving = session.logout();
    const result = leaving.catch((error) => error);
    for (const type of ['account-changing', 'account-changed'])
      listeners.forEach((listener) => listener(new MessageEvent('message', { data: { type } })));
    release();
    await blocker;
    expect(await result).toBeUndefined();
    expect(fetchImpl.mock.calls.filter(([path]) => path === '/api/v1/auth/logout')).toHaveLength(1);
    expect(session.getState().status).toBe('anonymous');
    expect(cookie).toBe(false);
  });
  it('входит и получает текущего пользователя из /me', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user));
    const { session } = setup(fetchImpl);
    await session.login('admin@school.ru', 'secret');
    expect(session.getState()).toMatchObject({
      status: 'authenticated',
      user,
      accessToken: 'access-token',
    });
    expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual([
      '/api/v1/auth/login',
      '/api/v1/auth/me',
    ]);
  });

  it('не запускает refresh после неправильного пароля', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      json(
        {
          error: {
            code: 'authentication_error',
            message: 'Invalid credentials',
            request_id: 'r1',
          },
        },
        401,
      ),
    );
    const { session } = setup(fetchImpl);
    await expect(session.login('admin@school.ru', 'bad')).rejects.toThrow();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(session.getState().status).toBe('anonymous');
  });

  it('восстанавливает сессию refresh → me', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user));
    const { session } = setup(fetchImpl);
    await session.bootstrap();
    expect(session.getAccessToken()).toBe('access-token');
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/v1/auth/refresh');
  });

  it('отличает отсутствие cookie от сетевого сбоя', async () => {
    const missing = setup(vi.fn<typeof fetch>().mockResolvedValue(json({}, 401))).session;
    await missing.bootstrap();
    expect(missing.getState().status).toBe('anonymous');
    const unavailable = setup(
      vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline')),
    ).session;
    await unavailable.bootstrap();
    expect(unavailable.getState().status).toBe('unavailable');
  });

  it('объединяет два одновременных refresh одной вкладки', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user));
    const { session } = setup(fetchImpl);
    await Promise.all([session.refresh(), session.refresh()]);
    expect(fetchImpl.mock.calls.filter(([path]) => path === '/api/v1/auth/refresh')).toHaveLength(
      1,
    );
  });

  it('сериализует cookie операции разных вкладок общим Web Lock', async () => {
    let active = 0;
    let maximum = 0;
    const fetchImpl = vi.fn<typeof fetch>(async (path) => {
      if (path === '/api/v1/auth/me') return json(user);
      active++;
      maximum = Math.max(active, maximum);
      await Promise.resolve();
      active--;
      return token();
    });
    const locks = new SharedLocks();
    await Promise.all([
      setup(fetchImpl, locks).session.bootstrap(),
      setup(fetchImpl, locks).session.bootstrap(),
    ]);
    expect(maximum).toBe(1);
  });

  it('не применяет ответ refresh после logout и очищает кеш', async () => {
    let finishRefresh!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finishRefresh = resolve;
    });
    const fetchImpl = vi.fn<typeof fetch>(async (path) => {
      if (path === '/api/v1/auth/refresh') return pending;
      if (path === '/api/v1/auth/logout') return new Response(null, { status: 204 });
      return json(user);
    });
    const { session, clear, queryClient } = setup(fetchImpl);
    queryClient.setQueryData(['old-account'], 'private');
    const refreshing = session.refresh().catch(() => undefined);
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    const loggingOut = session.logout();
    expect(session.getAccessToken()).toBeNull();
    finishRefresh(token());
    await Promise.all([refreshing, loggingOut]);
    expect(session.getState().status).toBe('anonymous');
    expect(clear).toHaveBeenCalled();
    expect(queryClient.getQueryData(['old-account'])).toBeUndefined();
  });

  it('очищает локальный доступ даже при неполном серверном отзыве', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user))
      .mockResolvedValueOnce(json({}, 503));
    const { session } = setup(fetchImpl);
    await session.login('admin@school.ru', 'secret');
    await expect(session.logout()).rejects.toThrow();
    expect(session.getState().status).toBe('anonymous');
    expect(session.getAccessToken()).toBeNull();
  });

  it('после неизвестного результата logout не восстанавливает аккаунт по чужому уведомлению', async () => {
    const listeners = new Set<(event: MessageEvent) => void>();
    const channel: SessionChannel = {
      postMessage: vi.fn(),
      addEventListener: (_, listener) => {
        listeners.add(listener);
      },
      removeEventListener: (_, listener) => {
        listeners.delete(listener);
      },
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user))
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const { session } = setup(fetchImpl, new SharedLocks(), channel);
    await session.login('admin@school.ru', 'secret');
    await expect(session.logout()).rejects.toThrow();
    for (const type of ['account-changing', 'account-changed'])
      listeners.forEach((listener) => listener(new MessageEvent('message', { data: { type } })));
    await Promise.resolve();
    expect(session.getState().status).toBe('anonymous');
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    await session.logout();
    expect(fetchImpl.mock.calls[3][0]).toBe('/api/v1/auth/logout');
    expect(session.getState().status).toBe('anonymous');
  });

  it('не использует ненадёжную самодельную блокировку вместо Web Locks', async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const { session } = setup(fetchImpl, null);
    await session.bootstrap();
    expect(session.getState()).toMatchObject({
      status: 'unavailable',
      message: expect.stringMatching(/браузер/i),
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('начинает новый bootstrap вместо ожидания устаревшего refresh', async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockReturnValueOnce(pending)
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user));
    const { session } = setup(fetchImpl);
    const oldBootstrap = session.bootstrap();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    session.invalidate();
    const newBootstrap = session.bootstrap();
    release(token());
    await Promise.all([oldBootstrap, newBootstrap]);
    expect(fetchImpl.mock.calls.filter(([path]) => path === '/api/v1/auth/refresh')).toHaveLength(
      2,
    );
    expect(session.getState().status).toBe('authenticated');
  });

  it('уведомляет другую вкладку о выходе без передачи токенов', async () => {
    const [firstChannel, secondChannel] = channels();
    const fetchImpl = vi.fn<typeof fetch>(async (path) =>
      path === '/api/v1/auth/me'
        ? json(user)
        : path === '/api/v1/auth/logout'
          ? new Response(null, { status: 204 })
          : token(),
    );
    const locks = new SharedLocks();
    const first = setup(fetchImpl, locks, firstChannel);
    const second = setup(fetchImpl, locks, secondChannel);
    await Promise.all([first.session.bootstrap(), second.session.bootstrap()]);
    second.queryClient.setQueryData(['private'], 'old');
    await first.session.logout();
    await vi.waitFor(() => expect(second.session.getState().status).toBe('anonymous'));
    expect(second.queryClient.getQueryData(['private'])).toBeUndefined();
    first.session.dispose();
    second.session.dispose();
  });

  it('очищает старые данные, если bootstrap обнаружил другой аккаунт', async () => {
    const other = { ...user, id: '704a1fbc-8faf-4b6b-a197-5e577f53eb30', email: 'other@school.ru' };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(user))
      .mockResolvedValueOnce(token())
      .mockResolvedValueOnce(json(other));
    const { session, queryClient } = setup(fetchImpl);
    await session.login('admin@school.ru', 'secret');
    queryClient.setQueryData(['account-private'], 'old-account-data');
    await session.bootstrap();
    expect(session.getState()).toMatchObject({ status: 'authenticated', user: other });
    expect(queryClient.getQueryData(['account-private'])).toBeUndefined();
  });
});
