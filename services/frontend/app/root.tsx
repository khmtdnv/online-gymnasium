import type { ReactNode } from 'react';
import { Links, Meta, Outlet, Scripts, ScrollRestoration } from 'react-router';
import './styles/app.css';
import { BrowserProviders } from './features/auth/session-context';
import { FeaturesProvider } from './lib/api/context';
import { AsyncState } from './components/async-state';

/* --- Тема: тёмная «Кварто» (navy/fog/aqua) по умолчанию, светлая «туманная» — по переключателю. --- */

export type Theme = 'light' | 'dark';
export const THEME_STORAGE_KEY = 'og-theme';

/** Inline-скрипт для <head>: ставит data-theme ДО загрузки бандла (нет FOUC).
 * Тема по умолчанию — тёмная «Кварто»: navy/fog/aqua из дизайн-системы. */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var s=localStorage.getItem('${THEME_STORAGE_KEY}');var t=s==='light'?'light':'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'dark' ? 'dark' : stored === 'light' ? 'light' : null;
  } catch {
    return null;
  }
}

/** Применяет тему к <html> и сохраняет выбор. Выбора нет — тёмная «Кварто». */
export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* приватный режим — тема живёт только в этой вкладке */
  }
}

export function currentTheme(): Theme {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

export function meta() {
  return [
    { title: 'Онлайн-гимназия' },
    { name: 'description', content: 'Расписание, нагрузка и справки об обучении.' },
  ];
}

export function ErrorBoundary() {
  return (
    <main className="content">
      <AsyncState
        state="error"
        title="Не удалось открыть страницу"
        message="Обновите страницу. Если ошибка повторяется, вернитесь позже."
        onRetry={() => window.location.reload()}
      />
    </main>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#0d1a2b" />
        {/* Тема ставится до бандла и до первой отрисовки — мигание исключено. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return (
    <BrowserProviders>
      <FeaturesProvider>
        <Outlet />
      </FeaturesProvider>
    </BrowserProviders>
  );
}
