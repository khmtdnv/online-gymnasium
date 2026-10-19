import { Navigate } from 'react-router';
import { Brand } from '../components/app-shell';
import { AsyncState } from '../components/async-state';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { LoginForm } from '../features/auth/login-form';
import { useSession } from '../features/auth/session-context';

export default function Login() {
  const { state, session } = useSession();
  if (state.status === 'authenticated') return <Navigate to="/" replace />;
  return (
    <div className="login-layout">
      <section className="login-story">
        <Brand />
        <span className="eyebrow">Ваш школьный день</span>
        <h1>
          Больше ясности.
          <br />
          Меньше суеты.
        </h1>
        <p>Школьные дела в одном спокойном пространстве. Заходите — всё нужное будет под рукой.</p>
        <div className="login-pills">
          <span>Понятное расписание</span>
          <span>Справки онлайн</span>
          <span>Общий рабочий ритм</span>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-form">
          <span className="eyebrow">Рады видеть вас</span>
          <h2>Вход в гимназию</h2>
          <p>Используйте учётную запись, которую вам выдал администратор.</p>
          {state.status === 'checking' && <AsyncState state="loading" title="Проверяем сессию" />}
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
                <Alert tone="error">
                  {state.message}
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void session?.logout().catch(() => undefined);
                    }}
                  >
                    Повторить выход
                  </Button>
                </Alert>
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
          <p className="field-hint" style={{ marginTop: 28 }}>
            Сотрудник школы? <a href="/admin/">Войти в Backoffice</a>
          </p>
        </div>
      </section>
    </div>
  );
}
