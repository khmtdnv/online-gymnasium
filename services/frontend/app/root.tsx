import type { ReactNode } from 'react';
import { Links, Meta, Outlet, Scripts, ScrollRestoration } from 'react-router';
import './styles/app.css';
import { BrowserProviders } from './features/auth/session-context';
import { FeaturesProvider } from './lib/api/context';
import { AsyncState } from './components/async-state';

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
        <meta name="theme-color" content="#267b99" />
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
