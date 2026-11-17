import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { createQueryClient } from '../../lib/query-client';
import { createSessionManager, type SessionManager, type SessionState } from './session';

const checking: SessionState = { status: 'checking' };
const SessionContext = createContext<{
  session: SessionManager | null;
  state: SessionState;
} | null>(null);
const emptySubscribe = () => () => undefined;
const getChecking = () => checking;

export function SessionProvider({
  session,
  queryClient,
  children,
}: {
  session: SessionManager | null;
  queryClient: QueryClient;
  children: ReactNode;
}) {
  const state = useSyncExternalStore(
    session?.subscribe ?? emptySubscribe,
    session?.getState ?? getChecking,
    getChecking,
  );
  return (
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={{ session, state }}>{children}</SessionContext.Provider>
    </QueryClientProvider>
  );
}

/** Браузерные ресурсы создаются после hydration, а не при build-time render. */
export function BrowserProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  const [session, setSession] = useState<SessionManager | null>(null);
  useEffect(() => {
    const channel =
      typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('og-session') : null;
    const manager = createSessionManager({
      fetchImpl: window.fetch.bind(window),
      queryClient,
      locks: navigator.locks ?? null,
      channel,
    });
    setSession(manager);
    void manager.bootstrap();
    return () => {
      manager.dispose();
      channel?.close();
      queryClient.clear();
    };
  }, [queryClient]);
  return (
    <SessionProvider session={session} queryClient={queryClient}>
      {children}
    </SessionProvider>
  );
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error('SessionProvider отсутствует в дереве приложения.');
  return value;
}
