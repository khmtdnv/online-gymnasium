import { expect, test } from '@playwright/test';

// Проверяет настоящий proxy. Для mock UI используется отдельный набор ui-*.spec.ts.
test('dev proxy отдаёт модули Vite, но закрывает остальные скрытые файлы', async ({ request }) => {
  test.skip(process.env.E2E_DEV !== '1', 'Нужен настоящий Vite через dev proxy.');
  const optimized = await request.get('/node_modules/.vite/deps/react-router.js');
  expect(optimized.status()).toBe(200);
  expect(optimized.headers()['content-type']).toContain('javascript');
  const html = await (await request.get('/login')).text();
  const entry = html.match(/href="(\/node_modules\/\.pnpm\/[^"\s]+entry\.client\.tsx)"/);
  expect(entry, 'HTML должен ссылаться на клиентский entry React Router').not.toBeNull();
  const module = await request.get(entry![1]);
  expect(module.status()).toBe(200);
  expect(module.headers()['content-type']).toContain('javascript');
  for (const path of [
    '/.env',
    '/.git/config',
    '/node_modules/.private/file.js',
    '/node_modules/.vite/.env',
    '/node_modules/.pnpm/pkg/node_modules/.env',
  ])
    expect((await request.get(path)).status(), path).toBe(404);
});

test('настоящая страница входа рендерит форму, а не только HTML и фон', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Пароль', { exact: true })).toBeVisible();
  if (process.env.QA_SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.QA_SCREENSHOT_DIR}/login-live-${page.context().browser()!.browserType().name()}.png`,
      fullPage: true,
    });
});

test('SPA deep link сохраняется при reload', async ({ page }) => {
  await page.goto('/profile');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  await expect(page.locator('body')).not.toContainText('nginx');
});
test('private API закрыт, API 404 не подменяется HTML', async ({ request }) => {
  expect((await request.get('/internal/backoffice/users')).status()).toBe(404);
  const missing = await request.get('/api/v1/route-that-does-not-exist');
  expect(missing.status()).toBe(404);
  expect(missing.headers()['content-type']).toContain('application/json');
});
test('Django и его static обслуживаются отдельно от SPA', async ({ request }) => {
  const login = await request.get('/admin/login/');
  expect(login.status()).toBe(200);
  expect(await login.text()).toContain('csrfmiddlewaretoken');
  const css = await request.get('/static/admin/css/base.css');
  expect(css.status()).toBe(200);
  expect(css.headers()['content-type']).toContain('text/css');
});
