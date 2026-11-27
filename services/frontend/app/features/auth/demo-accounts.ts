/**
 * Витринные демо-учётки публичного портфолио-сайта (решение 2026-11-27,
 * `concepts_brief.md`). Пароль сознательно не секрет: он в allowlist
 * `.gitleaks.toml`. Источник значений — `DEMO_PASSWORD` и шаблоны email
 * в `tools/create_demo_data.py`; на сервере пароли учёток приводятся к нему
 * шагом из `deploy/public/README-runbook.md`. Демо-админ сюда не входит:
 * его вход — Backoffice `/admin/` с отдельным паролем.
 */
export const DEMO_LOGIN_PASSWORD = 'DemoSchool2026!';

export const demoAccounts = [
  { label: 'Учитель', email: 'teacher01@demo.og.test' },
  { label: 'Ученик', email: 'student01.1@demo.og.test' },
  { label: 'Родитель', email: 'parent01@demo.og.test' },
] as const;
