import { Navigate } from 'react-router';
import { BookOpen, Clock } from 'lucide-react';
import { AsyncState } from '../components/async-state';
import { Button } from '../components/ui/button';
import { LoginForm } from '../features/auth/login-form';
import { useSession } from '../features/auth/session-context';

/** Карточка входа по макету g01: одна колонка по центру, без тестовых аккаунтов. */
export default function Login() {
  const { state, session } = useSession();
  if (state.status === 'authenticated') return <Navigate to="/" replace />;
  return (
    <main className="login-canvas">
      <div className="login-card">
        <header className="login-card-head">
          <span className="login-emblem" aria-hidden="true">
            <BookOpen size={26} />
          </span>
          <span className="login-eyebrow">Единый учебный портал</span>
          <h1>Вход в гимназию</h1>
          <p>Используйте школьный email и пароль, выданные учебной частью</p>
        </header>
        {state.status === 'checking' && (
          <AsyncState state="loading" title="Проверяем сессию" />
        )}
        {state.status === 'unavailable' && (
          <AsyncState
            state="error"
            title="Не удалось проверить вход"
            message={state.message}
            onRetry={() => {
              void session?.bootstrap();
            }}
          />
        )}
        {state.status === 'anonymous' && (
          <>
            {state.message && (
              <div className="login-session-banner" role="status">
                <Clock size={18} aria-hidden="true" />
                <div>
                  <p>{state.message}</p>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void session?.logout().catch(() => undefined);
                    }}
                  >
                    Повторить выход
                  </Button>
                </div>
              </div>
            )}
            <LoginForm
              onLogin={(email, password) =>
                session
                  ? session.login(email, password)
                  : Promise.reject(new Error('Сессия ещё не готова.'))
              }
            />
          </>
        )}
        <p className="login-card-footnote">
          Сотрудник школы? <a href="/admin/">Войти в Backoffice</a>
        </p>
      </div>
    </main>
  );
}
