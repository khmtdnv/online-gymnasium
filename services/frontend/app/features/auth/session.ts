import type { QueryClient } from '@tanstack/react-query';
import type { CurrentUser } from '../../lib/api/contracts';
import { ApiError, SessionChangedError } from '../../lib/api/errors';
import { createAuthApi } from './auth-api';

export type SessionState =
  | { status: 'checking' }
  | { status: 'anonymous'; message?: string }
  | { status: 'authenticated'; user: CurrentUser; accessToken: string }
  | { status: 'unavailable'; message: string };

export interface CookieLocks {
  request<T>(name: string, operation: () => Promise<T>): Promise<T>;
}
export interface SessionChannel {
  postMessage(message: unknown): void;
  addEventListener(type: 'message', listener: (event: MessageEvent) => void): void;
  removeEventListener(type: 'message', listener: (event: MessageEvent) => void): void;
}
export interface SessionManager {
  bootstrap(): Promise<void>;
  login(email: string, password: string): Promise<void>;
  refresh(): Promise<string>;
  logout(): Promise<void>;
  invalidate(): void;
  getState(): SessionState;
  getAccessToken(): string | null;
  getEpoch(): number;
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

/** Координирует cookie одним замком, а данные вкладки защищает поколением сессии. */
export function createSessionManager({
  fetchImpl,
  queryClient,
  locks,
  channel,
}: {
  fetchImpl: typeof fetch;
  queryClient: Pick<QueryClient, 'clear'>;
  locks: CookieLocks | null;
  channel: SessionChannel | null;
}): SessionManager {
  const api = createAuthApi(fetchImpl);
  let state: SessionState = { status: 'checking' };
  let epoch = 0;
  // checking/unavailable скрывают интерфейс, но не стирают владельца кэша.
  let identity: string | null = null;
  let refreshFlight: Promise<string> | null = null;
  let bootstrapFlight: Promise<void> | null = null;
  let localOperation = 0;
  let logoutIntent: number | null = null;
  const listeners = new Set<() => void>();
  const setState = (next: SessionState) => {
    state = next;
    listeners.forEach((listener) => listener());
  };
  function invalidate() {
    epoch++;
    // Новая сессия не должна присоединяться к promise прошлого поколения.
    refreshFlight = null;
    bootstrapFlight = null;
    identity = null;
    queryClient.clear();
    setState({ status: 'anonymous' });
  }
  function assertEpoch(expected: number) {
    if (epoch !== expected) throw new SessionChangedError();
  }
  function withCookieLock<T>(operation: () => Promise<T>): Promise<T> {
    if (!locks)
      return Promise.reject(
        new Error(
          'Обновите браузер: для безопасной работы нескольких вкладок требуется Web Locks.',
        ),
      );
    return locks.request('og1-auth-cookie', operation);
  }
  async function authenticate(accessToken: string, expected: number) {
    assertEpoch(expected);
    const user = await api.me(accessToken);
    assertEpoch(expected);
    const nextIdentity = `${user.id}:${user.role}`;
    if (identity !== null && identity !== nextIdentity) {
      epoch++;
      queryClient.clear();
    }
    identity = nextIdentity;
    setState({ status: 'authenticated', user, accessToken });
  }
  function refresh(): Promise<string> {
    if (refreshFlight) return refreshFlight;
    const expected = epoch;
    const operation = withCookieLock(async () => {
      assertEpoch(expected);
      const { access_token } = await api.refresh();
      await authenticate(access_token, expected);
      return access_token;
    })
      .catch((error: unknown) => {
        if (epoch === expected) {
          if (error instanceof ApiError && error.status === 401) invalidate();
          else
            setState({
              status: 'unavailable',
              message: error instanceof Error ? error.message : 'Не удалось проверить сессию.',
            });
        }
        throw error;
      })
      .finally(() => {
        if (refreshFlight === operation) refreshFlight = null;
      });
    refreshFlight = operation;
    return operation;
  }
  function bootstrap(): Promise<void> {
    if (bootstrapFlight) return bootstrapFlight;
    const operation = (async () => {
      const expected = epoch;
      setState({ status: 'checking' });
      try {
        await refresh();
      } catch (error) {
        if (error instanceof SessionChangedError || epoch !== expected) return;
        // refresh уже различил anonymous и unavailable.
      }
    })().finally(() => {
      if (bootstrapFlight === operation) bootstrapFlight = null;
    });
    bootstrapFlight = operation;
    return operation;
  }
  async function login(email: string, password: string) {
    localOperation++;
    logoutIntent = null;
    invalidate();
    const expected = epoch;
    channel?.postMessage({ type: 'account-changing' });
    try {
      await withCookieLock(async () => {
        assertEpoch(expected);
        const { access_token } = await api.login(email, password);
        await authenticate(access_token, expected);
      });
      assertEpoch(expected);
      channel?.postMessage({ type: 'account-changed' });
    } catch (error) {
      if (epoch === expected) setState({ status: 'anonymous' });
      throw error;
    }
  }
  async function logout() {
    const operation = ++localOperation;
    logoutIntent = operation;
    invalidate();
    channel?.postMessage({ type: 'logout' });
    try {
      await withCookieLock(async () => {
        // Отложенный logout всё равно отзывает cookie после предыдущей операции.
        // Событие чужой вкладки не отменяет явное намерение пользователя выйти.
        await api.logout();
      });
      if (logoutIntent === operation) logoutIntent = null;
      channel?.postMessage({ type: 'logout' });
    } catch (error) {
      if (logoutIntent === operation)
        setState({
          status: 'anonymous',
          message:
            'Локальный выход выполнен, но серверный отзыв сессии не подтверждён. Повторите выход после восстановления связи.',
        });
      throw error;
    }
  }
  function receive(event: MessageEvent) {
    const type =
      typeof event.data === 'object' && event.data !== null ? event.data.type : undefined;
    // BroadcastChannel доставляет сообщения отдельными tasks: они могут запоздать
    // относительно lock queue. До подтверждённого выхода (или нового login)
    // такие уведомления не имеют права снова запустить bootstrap.
    if (logoutIntent !== null && (type === 'account-changing' || type === 'account-changed'))
      return;
    if (type === 'logout' || type === 'account-changing') invalidate();
    if (type === 'account-changed') {
      invalidate();
      void bootstrap();
    }
  }
  channel?.addEventListener('message', receive);
  return {
    bootstrap,
    login,
    refresh,
    logout,
    invalidate,
    getState: () => state,
    getAccessToken: () => (state.status === 'authenticated' ? state.accessToken : null),
    getEpoch: () => epoch,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose: () => {
      channel?.removeEventListener('message', receive);
      listeners.clear();
    },
  };
}
