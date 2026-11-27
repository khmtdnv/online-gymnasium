import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInThisContext } from 'node:vm';
import { createElement } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { AppShell } from '../app/components/app-shell';
import {
  THEME_BOOTSTRAP_SCRIPT,
  THEME_STORAGE_KEY,
  applyTheme,
  currentTheme,
  readStoredTheme,
} from '../app/root';

const rootSource = readFileSync(join(process.cwd(), 'app/root.tsx'), 'utf-8');
const tokensSource = readFileSync(join(process.cwd(), 'app/styles/tokens.css'), 'utf-8');

/** Тот же код, что выполняется инлайн в <head> до загрузки бандла. */
function runBootstrap() {
  runInThisContext(THEME_BOOTSTRAP_SCRIPT);
}

it('bootstrap ставит тёмную тему из localStorage до первой отрисовки', () => {
  document.documentElement.removeAttribute('data-theme');
  localStorage.setItem(THEME_STORAGE_KEY, 'dark');
  runBootstrap();
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
});

it('без выбора в localStorage bootstrap ставит тёмную тему «Кварто»', () => {
  document.documentElement.removeAttribute('data-theme');
  localStorage.clear();
  runBootstrap();
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
});

it('некорректное значение в localStorage трактуется как тёмная тема', () => {
  document.documentElement.removeAttribute('data-theme');
  localStorage.setItem(THEME_STORAGE_KEY, 'blue');
  runBootstrap();
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
});

it('inline-скрипт темы стоит в head раньше бандла и не тянет внешний src', () => {
  // FOUC исключён конструктивно: скрипт объявлен в Layout до <Scripts />.
  const scriptAt = rootSource.indexOf('THEME_BOOTSTRAP_SCRIPT');
  const scriptsAt = rootSource.indexOf('<Scripts />');
  expect(scriptAt).toBeGreaterThan(-1);
  expect(scriptsAt).toBeGreaterThan(scriptAt);
  // Инлайн-скрипт без src: внешний CDN не подключается.
  expect(rootSource).toMatch(
    /<script dangerouslySetInnerHTML=\{\{ __html: THEME_BOOTSTRAP_SCRIPT \}\} \/>/,
  );
  expect(THEME_BOOTSTRAP_SCRIPT).not.toMatch(/src=|https?:\/\//);
  expect(THEME_BOOTSTRAP_SCRIPT).toContain('localStorage.getItem');
  expect(THEME_BOOTSTRAP_SCRIPT).toContain("setAttribute('data-theme'");
});

it('токены содержат значения «Кварто» (navy/fog/aqua) для тёмной темы', () => {
  expect(tokensSource).toContain("[data-theme='dark']");
  const dark = tokensSource.slice(tokensSource.indexOf('[data-theme=', 1));
  expect(dark).toContain('--canvas: #0d1a2b');
  expect(dark).toContain('--text: #d9e2ef');
  expect(dark).toContain('--accent: #37e0d0');
});

it('applyTheme обновляет атрибут и localStorage, выбор читается обратно', () => {
  applyTheme('dark');
  expect(currentTheme()).toBe('dark');
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  expect(readStoredTheme()).toBe('dark');
  applyTheme('light');
  expect(currentTheme()).toBe('light');
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
});

it('переключатель в оболочке обновляет атрибут и localStorage', async () => {
  document.documentElement.setAttribute('data-theme', 'light');
  localStorage.clear();
  const keyboard = userEvent.setup();
  const user = {
    id: '6c6f3434-e4cc-4619-8c2a-8d733913ecda',
    email: 'admin@school.ru',
    role: 'admin' as const,
  };
  render(
    createElement(
      MemoryRouter,
      null,
      createElement(AppShell, {
        user,
        onLogout: vi.fn(),
        children: createElement('h1', null, 'Главная'),
      }),
    ),
  );
  const toggle = screen.getByRole('button', { name: /Переключить на тёмную/ });
  expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await keyboard.click(toggle);
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  const back = screen.getByRole('button', { name: /Переключить на светлую/ });
  expect(back).toHaveAttribute('aria-pressed', 'true');
  await keyboard.click(back);
  expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
});
