import { PageHeader } from '../components/page-header';
import { roleLabels } from '../components/app-shell';
import { useSession } from '../features/auth/session-context';

export default function Profile() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  return (
    <>
      <PageHeader
        title="Ваш профиль"
        eyebrow="Учётная запись"
        description="Текущие данные из Gateway. Изменение профиля в портале пока не подключено."
      />
      <section className="card">
        <dl className="detail-list">
          <div>
            <dt>Email</dt>
            <dd>{state.user.email}</dd>
          </div>
          <div>
            <dt>Роль</dt>
            <dd>{roleLabels[state.user.role]}</dd>
          </div>
          <div>
            <dt>ID пользователя</dt>
            <dd>{state.user.id}</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
