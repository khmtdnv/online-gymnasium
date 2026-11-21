import { Mail, ShieldCheck, UserRound } from 'lucide-react';
import { PageHeader } from '../components/page-header';
import { roleLabels } from '../components/app-shell';
import { useSession } from '../features/auth/session-context';

export default function Profile() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  const { user } = state;
  const fullName = [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(' ');
  return (
    <div className="workspace-page profile-page">
      <PageHeader title="Ваш профиль" description="Информация о вашей учётной записи." />
      <div className="profile-layout">
        <section className="profile-identity">
          <div className="profile-avatar" aria-hidden="true">
            {(user.first_name || user.email)[0].toUpperCase()}
          </div>
          <span className="profile-role">{roleLabels[user.role]}</span>
          <h2>{fullName || 'Личный кабинет'}</h2>
          <p>{user.email}</p>
        </section>
        <section className="workspace-panel profile-details">
          <div className="workspace-panel-head">
            <div>
              <span className="workspace-kicker">Учётная запись</span>
              <h2>Данные профиля</h2>
            </div>
          </div>
          <div className="profile-field">
            <span className="workspace-icon">
              <UserRound size={19} />
            </span>
            <div>
              <span>Фамилия</span>
              <strong>{user.last_name || 'Не указана'}</strong>
            </div>
          </div>
          <div className="profile-field">
            <span className="workspace-icon">
              <UserRound size={19} />
            </span>
            <div>
              <span>Имя</span>
              <strong>{user.first_name || 'Не указано'}</strong>
            </div>
          </div>
          <div className="profile-field">
            <span className="workspace-icon">
              <UserRound size={19} />
            </span>
            <div>
              <span>Отчество</span>
              <strong>{user.middle_name || 'Не указано'}</strong>
            </div>
          </div>
          <div className="profile-field">
            <span className="workspace-icon">
              <Mail size={19} />
            </span>
            <div>
              <span>Электронная почта</span>
              <strong>{user.email}</strong>
            </div>
          </div>
          <div className="profile-field">
            <span className="workspace-icon">
              <UserRound size={19} />
            </span>
            <div>
              <span>Роль</span>
              <strong>{roleLabels[user.role]}</strong>
            </div>
          </div>
          <div className="profile-help">
            <ShieldCheck size={19} />
            <p>Если данные указаны неверно, обратитесь к администратору школы.</p>
          </div>
          <details className="profile-technical">
            <summary>Техническая информация</summary>
            <span>ID пользователя: {user.id}</span>
          </details>
        </section>
      </div>
    </div>
  );
}
