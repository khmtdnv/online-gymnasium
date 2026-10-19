import { Link, Outlet } from 'react-router';
import { AsyncState } from '../components/async-state';
import { useSession } from '../features/auth/session-context';

export default function OperationalLayout() {
  const { state } = useSession();
  if (state.status !== 'authenticated' || state.user.role !== 'admin')
    return (
      <>
        <AsyncState
          state="error"
          title="Нет доступа"
          message="Этот раздел пока доступен только администратору. Личные данные классов будут подключены отдельным этапом."
        />
        <Link to="/" className="button button-secondary">
          На главную
        </Link>
      </>
    );
  return <Outlet />;
}
