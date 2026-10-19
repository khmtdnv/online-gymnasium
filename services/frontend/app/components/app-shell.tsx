import * as Dialog from '@radix-ui/react-dialog';
import {
  CalendarDays,
  ChartNoAxesCombined,
  Files,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  UserRound,
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
    <Link to="/" className="brand" aria-label="OG1 · Онлайн-гимназия">
      <span className="brand-mark">
        <GraduationCap size={27} aria-hidden="true" />
      </span>
      <div>
        <strong>OG1</strong>
        <span>Онлайн-гимназия</span>
      </div>
    </Link>
  );
}

/** Показывает только доступные ссылки; сервер всё равно обязан проверять роль. */
export function AppShell({
  user,
  children,
  onLogout,
}: {
  user: CurrentUser;
  children: ReactNode;
  onLogout: () => Promise<void>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const links = [
    { to: '/', label: 'Главная', icon: LayoutDashboard },
    ...(user.role === 'admin'
      ? [
          { to: '/schedule', label: 'Расписание', icon: CalendarDays },
          { to: '/workload', label: 'Нагрузка', icon: ChartNoAxesCombined },
          { to: '/documents', label: 'Справки', icon: Files },
        ]
      : []),
    { to: '/profile', label: 'Профиль', icon: UserRound },
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
        <a href="/admin/" className="nav-link">
          <Settings size={21} aria-hidden="true" />
          Администрирование
        </a>
      )}
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
      <aside className="sidebar">
        <Brand />
        <p className="nav-caption">Рабочее пространство</p>
        {navigation}
        <div className="sidebar-footer">
          <div className="sidebar-note">
            <GraduationCap size={25} aria-hidden="true" />
            <p>Учёба и школьные дела — спокойно, по порядку.</p>
          </div>
          <Button variant="ghost" onClick={logout} disabled={leaving}>
            <LogOut size={20} aria-hidden="true" />
            Выйти
          </Button>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
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
          <span className="topbar-label">OG1 / ваше пространство</span>
          <div className="account">
            <div className="account-info">
              <strong>{user.email}</strong>
              <span>{roleLabels[user.role]}</span>
            </div>
            <span className="avatar" aria-hidden="true">
              {user.email[0].toUpperCase()}
            </span>
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
