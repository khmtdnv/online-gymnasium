import * as Dialog from '@radix-ui/react-dialog';
import {
  CalendarDays,
  ChartNoAxesCombined,
  Files,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  X,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { NavLink, Link } from 'react-router';
import type { CurrentUser } from '../lib/api/contracts';
import { Button } from './ui/button';
import { Alert } from './ui/alert';

export const roleLabels = {
  admin: 'Администратор',
  student: 'Ученик',
  teacher: 'Учитель',
  parent: 'Родитель',
} as const;

export function Brand() {
  return (
    <Link to="/" className="brand" aria-label="Онлайн-гимназия">
      <span className="brand-mark">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 6.2C10.4 4.9 8.2 4.3 5.4 4.3c-.8 0-1.4.6-1.4 1.4v10.5c0 .8.6 1.3 1.4 1.3 2.8 0 5 .6 6.6 1.9 1.6-1.3 3.8-1.9 6.6-1.9.8 0 1.4-.5 1.4-1.3V5.7c0-.8-.6-1.4-1.4-1.4-2.8 0-5 .6-6.6 1.9Z"
            fill="currentColor"
          />
          <path d="M12 6.2v13.2" stroke="var(--accent)" strokeWidth="1.6" />
        </svg>
      </span>
      <div>
        <strong>Онлайн-гимназия</strong>
      </div>
    </Link>
  );
}

/** Показывает только доступные ссылки; сервер всё равно обязан проверять роль. */
export function AppShell({
  user,
  children,
  onLogout,
  onEnterAdmin,
  notificationControl,
}: {
  user: CurrentUser;
  children: ReactNode;
  onLogout: () => Promise<void>;
  onEnterAdmin?: (target: string) => Promise<void>;
  notificationControl?: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const [adminError, setAdminError] = useState(false);
  async function openAdmin(event: React.MouseEvent<HTMLAnchorElement>, target: string) {
    if (!onEnterAdmin) return;
    event.preventDefault();
    setAdminError(false);
    try {
      await onEnterAdmin(target);
    } catch {
      setAdminError(true);
    }
  }
  const links = [
    { to: '/', label: 'Главная', icon: LayoutDashboard },
    ...(user.role === 'admin'
      ? [
          { to: '/schedule', label: 'Расписание', icon: CalendarDays },
          { to: '/workload', label: 'Нагрузка', icon: ChartNoAxesCombined },
          { to: '/documents', label: 'Документы', icon: Files },
        ]
      : []),
    ...(['teacher', 'student'].includes(user.role)
      ? [
          { to: '/schedule', label: 'Моё расписание', icon: CalendarDays },
          {
            to: '/homework',
            label: user.role === 'teacher' ? 'Уроки и проверка ДЗ' : 'Домашние задания',
            icon: Files,
          },
        ]
      : []),
    ...(['student', 'parent'].includes(user.role)
      ? [{ to: '/billing', label: 'Оплата обучения', icon: Files }]
      : []),
  ];
  const navigation = (
    <nav aria-label="Основные разделы" className="nav-links">
      {links.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          onClick={() => setMenuOpen(false)}
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          <Icon size={21} aria-hidden="true" />
          {label}
        </NavLink>
      ))}
      {user.role === 'admin' && (
        <>
          <a
            href="/admin/analytics/"
            className="nav-link"
            onClick={(event) => void openAdmin(event, '/admin/analytics/')}
          >
            <ChartNoAxesCombined size={21} aria-hidden="true" />
            Успеваемость и аудит
          </a>
          <a
            href="/admin/payments/"
            className="nav-link"
            onClick={(event) => void openAdmin(event, '/admin/payments/')}
          >
            <Files size={21} aria-hidden="true" />
            История платежей
          </a>
          <a
            href="/admin/"
            className="nav-link"
            onClick={(event) => void openAdmin(event, '/admin/')}
          >
            <Settings size={21} aria-hidden="true" />
            Администрирование
          </a>
        </>
      )}
      {adminError && <p role="alert">Не удалось войти в админку. Проверьте права и соединение.</p>}
    </nav>
  );
  async function logout() {
    setLeaving(true);
    try {
      await onLogout();
    } catch {
      setLogoutError(true);
    } finally {
      setLeaving(false);
    }
  }
  return (
    <div className="app-layout">
      <a href="#main-content" className="skip-link">
        Перейти к содержимому
      </a>
      <div className="app-body">
        <header className="topbar">
          <div className="desktop-brand">
            <Brand />
          </div>
          <div className="desktop-navigation">{navigation}</div>
          <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
            <Dialog.Trigger asChild>
              <Button
                variant="ghost"
                className="icon-button mobile-trigger"
                aria-label="Открыть меню"
              >
                <Menu aria-hidden="true" />
              </Button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="dialog-overlay" />
              <Dialog.Content className="dialog-content mobile-navigation">
                <Dialog.Title className="sr-only">Навигация</Dialog.Title>
                <Dialog.Description className="sr-only">Разделы онлайн-гимназии</Dialog.Description>
                <Brand />
                {navigation}
                <Button variant="ghost" onClick={logout} disabled={leaving}>
                  <LogOut size={20} aria-hidden="true" />
                  Выйти
                </Button>
                <Dialog.Close asChild>
                  <Button
                    variant="ghost"
                    className="icon-button dialog-close"
                    aria-label="Закрыть меню"
                  >
                    <X aria-hidden="true" />
                  </Button>
                </Dialog.Close>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <span className="topbar-label">
            Онлайн-гимназия <span aria-hidden="true">/</span> Личный кабинет
          </span>
          <div className="account">
            {notificationControl}
            <Link to="/profile" className="account-link" aria-label="Профиль">
              <div className="account-info">
                <strong>
                  {[user.first_name, user.last_name].filter(Boolean).join(' ') || user.email}
                </strong>
                <span>{roleLabels[user.role]}</span>
              </div>
              <span className="avatar" aria-hidden="true">
                {(user.first_name || user.email)[0].toUpperCase()}
              </span>
            </Link>
            <Button variant="ghost" className="desktop-logout" onClick={logout} disabled={leaving}>
              Выйти
            </Button>
          </div>
        </header>
        <main id="main-content" className="content" tabIndex={-1}>
          {logoutError && (
            <Alert tone="error">
              Не удалось подтвердить отзыв сессии на сервере. Повторите выход, когда связь
              восстановится.
            </Alert>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
