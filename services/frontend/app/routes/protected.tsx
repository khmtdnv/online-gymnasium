import { Navigate, Outlet } from 'react-router';
import { AppShell } from '../components/app-shell';
import { AsyncState } from '../components/async-state';
import { enterBackoffice, readCsrfCookie } from '../features/auth/backoffice-sso';
import { useSession } from '../features/auth/session-context';

export default function ProtectedLayout() {
  const { state, session } = useSession();
  if (state.status === 'checking')
    return (
      <main className="content">
        <AsyncState state="loading" title="Открываем ваше пространство" />
      </main>
    );
  if (state.status === 'unavailable')
    return (
      <main className="content">
        <AsyncState
          state="error"
          title="Проверка сессии недоступна"
          message={state.message}
          onRetry={() => {
            void session?.bootstrap();
          }}
        />
      </main>
    );
  if (state.status === 'anonymous') return <Navigate to="/login" replace />;
  return (
    <AppShell
      user={state.user}
      onLogout={() => (session ? session.logout() : Promise.resolve())}
      onEnterAdmin={async (target) => {
        if (!session) throw new Error('Сессия недоступна.');
        const accessToken = await session.refresh();
        await enterBackoffice(
          target,
          accessToken,
          window.fetch.bind(window),
          readCsrfCookie,
          (url) => window.location.assign(url),
        );
      }}
    >
      <Outlet />
    </AppShell>
  );
}
