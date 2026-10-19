import { expect, test, type BrowserContext, type Page } from '@playwright/test';

const user = {
  id: 'a28b23b3-9d1b-4fb2-8d44-4c1ea874a071',
  email: 'admin@example.test',
  role: 'admin',
};
const lesson = {
  id: 901,
  class_id: 21,
  teacher_id: '8df96b7a-7d30-44e7-b577-f6581300e101',
  subject_id: 41,
  starts_at: '2026-10-03T08:00:00Z',
  ends_at: '2026-10-03T08:45:00Z',
  status: 'planned',
  version: 1,
};

async function mockBackend(context: BrowserContext, role = 'admin') {
  let loggedIn = false;
  let logoutFails = false;
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/login')) {
      loggedIn = true;
      await route.fulfill({ json: { access_token: 'browser-test-token' } });
    } else if (path.endsWith('/refresh')) {
      await route.fulfill(
        loggedIn
          ? { json: { access_token: 'refreshed-test-token' } }
          : {
              status: 401,
              json: {
                error: { code: 'authentication_error', message: 'No session', request_id: 'qa' },
              },
            },
      );
    } else if (path.endsWith('/logout')) {
      if (logoutFails) await route.abort();
      else {
        loggedIn = false;
        await route.fulfill({ status: 204 });
      }
    } else if (path.endsWith('/me')) await route.fulfill({ json: { ...user, role } });
    else if (path.includes('/schedule/lessons')) await route.fulfill({ json: [lesson] });
    else if (path.endsWith('/workload'))
      await route.fulfill({
        json: {
          class_id: 21,
          day: '2026-10-03',
          planned_lessons_count: 1,
          planned_minutes: 45,
          refreshed_at: '2026-10-03T08:00:00',
        },
      });
    else
      await route.fulfill({
        status: 404,
        json: { error: { code: 'not_found', message: 'Missing', request_id: 'qa' } },
      });
  });
  return {
    failLogout: () => {
      logoutFails = true;
    },
  };
}
async function login(page: Page) {
  await page.goto('/login');
  if (
    process.env.QA_SCREENSHOT_DIR &&
    page.context().browser()?.browserType().name() === 'chromium'
  ) {
    await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
    await page.screenshot({ path: `${process.env.QA_SCREENSHOT_DIR}/login.png`, fullPage: true });
  }
  await page.getByLabel('Email', { exact: true }).fill(user.email);
  await page.getByLabel('Пароль', { exact: true }).fill('synthetic-test-password');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Онлайн-гимназия');
}

test('UI mock: login/reload/logout и память без persisted JWT', async ({ page, context }) => {
  await mockBackend(context);
  await login(page);
  await page.reload();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Онлайн-гимназия');
  // React Router может хранить положение прокрутки; проверяем именно секреты,
  // а не запрещаем безопасное состояние интерфейса.
  expect(
    await page.evaluate(() =>
      [localStorage, sessionStorage]
        .flatMap((storage) => Object.values(storage))
        .some((value) =>
          [
            'browser-test-token',
            'refreshed-test-token',
            'synthetic-test-password',
            'admin@example.test',
          ].some((secret) => value.includes(secret)),
        ),
    ),
  ).toBe(false);
  await page.getByRole('button', { name: 'Выйти', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
});
test('UI mock: logout в одной вкладке очищает вторую', async ({ page, context }) => {
  await mockBackend(context);
  await login(page);
  const second = await context.newPage();
  await second.goto('/profile');
  await expect(second.getByRole('heading', { level: 1 })).toHaveText('Ваш профиль');
  await page.getByRole('button', { name: 'Выйти', exact: true }).first().click();
  await expect(second.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
});
test('UI mock: ограниченная роль не запрашивает расписание через direct URL', async ({
  page,
  context,
}) => {
  let operationalRequests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/schedule/lessons')) operationalRequests++;
  });
  await mockBackend(context, 'student');
  await login(page);
  await page.goto('/schedule?class_id=21&day=2026-10-03');
  await expect(page.getByRole('heading', { name: 'Нет доступа' })).toBeVisible();
  expect(operationalRequests).toBe(0);
});
test('UI mock: мобильное меню закрывается Escape и возвращает фокус', async ({ page, context }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mockBackend(context);
  await login(page);
  const trigger = page.getByRole('button', { name: 'Открыть меню' });
  await trigger.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
test('UI mock: ширины 360/768/1440 и reduced motion без горизонтального скролла', async ({
  page,
  context,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockBackend(context);
  await login(page);
  if (
    process.env.QA_SCREENSHOT_DIR &&
    page.context().browser()?.browserType().name() === 'chromium'
  )
    await page.screenshot({ path: `${process.env.QA_SCREENSHOT_DIR}/home.png`, fullPage: true });
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/schedule?class_id=21&day=2026-10-03');
    await expect(page.getByRole('heading', { name: 'Расписание', exact: true })).toBeVisible();
    await expect(page.locator('.lesson-time')).toContainText('08:00');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    if (
      process.env.QA_SCREENSHOT_DIR &&
      page.context().browser()?.browserType().name() === 'chromium'
    )
      await page.screenshot({
        path: `${process.env.QA_SCREENSHOT_DIR}/schedule-${width}.png`,
        fullPage: true,
      });
  }
});
