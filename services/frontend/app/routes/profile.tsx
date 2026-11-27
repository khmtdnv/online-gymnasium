import { useState } from 'react';
import { AtSign, BadgeCheck, ChevronDown, LogOut, ShieldCheck } from 'lucide-react';
import { PageHeader } from '../components/page-header';
import { roleLabels } from '../components/app-shell';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import type { Role } from '../lib/api/contracts';

const roleHints: Record<Role, string> = {
  student: 'Дневник, расписание и домашние задания',
  teacher: 'Уроки, проверка работ и умная ручка',
  parent: 'Оплата, документы и уведомления',
  admin: 'Расписание, документы и аналитика',
};

/** Профиль по макету g03: карточка-удостоверение, подсказка об администраторе, свёрнутый ID. */
export default function Profile() {
  const { state, session } = useSession();
  const [leaving, setLeaving] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  if (state.status !== 'authenticated') return null;
  const { user } = state;
  const fullName = [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(' ');
  const displayName = fullName || 'Личный кабинет';
  const initials =
    [user.first_name?.[0], user.last_name?.[0]]
      .filter((letter): letter is string => typeof letter === 'string')
      .join('')
      .toUpperCase() || user.email[0].toUpperCase();
  async function logout() {
    setLeaving(true);
    setLogoutError(false);
    try {
      await (session ? session.logout() : Promise.resolve());
    } catch {
      setLogoutError(true);
    } finally {
      setLeaving(false);
    }
  }
  return (
    <div className="workspace-page profile-page">
      <PageHeader
        eyebrow="Академический реестр"
        title="Личное дело"
        description="Учётная запись и данные пользователя портала."
      />
      <div className="profile-layout">
        <div className="profile-rail">
          <section className="profile-pass">
            <span className="profile-pass-bar" aria-hidden="true" />
            <div className="profile-avatar" aria-hidden="true">
              {initials}
            </div>
            <span className="profile-kicker">{roleLabels[user.role]}</span>
            <h2>{displayName}</h2>
            <p className="profile-pass-email">{user.email}</p>
          </section>
          <section className="profile-notice">
            <ShieldCheck size={20} aria-hidden="true" />
            <div>
              <h3>Порядок изменения данных</h3>
              <p>
                Если ФИО или email указаны неверно, обратитесь к администратору школы: изменения
                вносит учебная часть через Backoffice.
              </p>
            </div>
          </section>
          {logoutError && (
            <p role="alert" className="profile-logout-error">
              Не удалось выйти из учётной записи. Повторите ещё раз.
            </p>
          )}
          <Button variant="secondary" className="profile-logout" onClick={logout} disabled={leaving}>
            <LogOut size={18} aria-hidden="true" />
            {leaving ? 'Выходим…' : 'Выйти из учетной записи'}
          </Button>
        </div>
        <div className="profile-ledger">
          <section className="workspace-panel profile-sheet">
            <div className="profile-sheet-head">
              <h3>Учетные данные</h3>
              <span className="profile-sheet-index">Лист 1 // Идентификация</span>
            </div>
            <div className="profile-tile profile-tile--wide">
              <span>Фамилия, имя и отчество полностью</span>
              <strong>{fullName || user.email}</strong>
            </div>
            <div className="profile-tiles">
              <div className="profile-tile">
                <div className="profile-tile-head">
                  <span>Школьный email</span>
                  <AtSign size={16} aria-hidden="true" />
                </div>
                <strong>{user.email}</strong>
                <small>Единая учётная запись портала</small>
              </div>
              <div className="profile-tile">
                <div className="profile-tile-head">
                  <span>Роль в системе</span>
                  <BadgeCheck size={16} aria-hidden="true" />
                </div>
                <strong>{roleLabels[user.role]}</strong>
                <small>{roleHints[user.role]}</small>
              </div>
            </div>
          </section>
          <details className="profile-technical">
            <summary>
              <span className="profile-technical-heading">
                <strong>Технические сведения учетной записи</strong>
                <small>Служебные идентификаторы вашей записи</small>
              </span>
              <span className="profile-technical-toggle">
                <span className="toggle-collapsed">Развернуть</span>
                <span className="toggle-open">Свернуть</span>
                <ChevronDown size={16} aria-hidden="true" />
              </span>
            </summary>
            <div className="profile-technical-body">
              <div className="profile-technical-row">
                <span>ID пользователя</span>
                <code>{user.id}</code>
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
