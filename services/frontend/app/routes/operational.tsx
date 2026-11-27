import { Link, Outlet } from 'react-router';
import { AsyncState } from '../components/async-state';
import { useSession } from '../features/auth/session-context';

/** Экран «нет прав» в едином шаблоне состояний; доступ проверяет сервер. */
export default function OperationalLayout() {
  const { state } = useSession();
  if (state.status !== 'authenticated' || state.user.role !== 'admin')
    return (
      <div className="workspace-page state-page">
        <AsyncState
          state="error"
          title="Нет доступа"
          message="Этот раздел пока доступен только администратору. Личные данные классов будут подключены отдельным этапом."
        />
        <div className="form-actions">
          <Link to="/" className="button button-secondary">
            На главную
          </Link>
        </div>
      </div>
    );
  return <Outlet />;
}
