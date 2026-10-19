import { Navigate, Outlet } from 'react-router';
import { AppShell } from '../components/app-shell';
import { AsyncState } from '../components/async-state';
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
    <AppShell user={state.user} onLogout={() => (session ? session.logout() : Promise.resolve())}>
      <Outlet />
    </AppShell>
  );
}
