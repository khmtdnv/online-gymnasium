import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LoginForm } from '../app/features/auth/login-form';
import { ApiError } from '../app/lib/api/errors';

describe('форма входа', () => {
  it('передаёт данные и очищает пароль после успешной попытки', async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    render(<LoginForm onLogin={login} />);
    await userEvent.type(screen.getByLabelText('Email'), 'admin@school.ru');
    await userEvent.type(screen.getByLabelText('Пароль'), 'secret');
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }));
    expect(login).toHaveBeenCalledWith('admin@school.ru', 'secret');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('показывает русское сообщение вместо detail сервера и не сохраняет пароль', async () => {
    const login = vi.fn().mockRejectedValue(new Error('internal technical error'));
    render(<LoginForm onLogin={login} />);
    await userEvent.type(screen.getByLabelText('Email'), 'admin@school.ru');
    await userEvent.type(screen.getByLabelText('Пароль'), 'bad');
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }));
    expect(screen.getByRole('alert')).not.toHaveTextContent('internal technical error');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('сообщает о неверном логине или пароле при 401', async () => {
    const login = vi
      .fn()
      .mockRejectedValue(new ApiError(401, 'invalid_credentials', 'Неверные учетные данные.'));
    render(<LoginForm onLogin={login} />);
    await userEvent.type(screen.getByLabelText('Email'), 'admin@school.ru');
    await userEvent.type(screen.getByLabelText('Пароль'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }));
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Email или пароль не подошли');
    expect(alert).not.toHaveTextContent('Неверные учетные данные');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('показывает и скрывает пароль доступным контролом', async () => {
    render(<LoginForm onLogin={vi.fn()} />);
    const password = screen.getByLabelText('Пароль');
    await userEvent.type(password, 'secret');
    expect(password).toHaveAttribute('type', 'password');
    const toggle = screen.getByRole('button', { name: 'Показать/скрыть пароль' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(toggle);
    expect(password).toHaveAttribute('type', 'text');
    expect(password).toHaveValue('secret');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(toggle);
    expect(password).toHaveAttribute('type', 'password');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
  });

  it('блокирует повторную отправку, пока вход выполняется', async () => {
    const login = vi.fn(() => new Promise<void>(() => undefined));
    render(<LoginForm onLogin={login} />);
    await userEvent.type(screen.getByLabelText('Email'), 'admin@school.ru');
    await userEvent.type(screen.getByLabelText('Пароль'), 'secret');
    const submit = screen.getByRole('button', { name: 'Войти' });
    await userEvent.click(submit);
    expect(submit).toBeDisabled();
    expect(submit).toHaveTextContent('Входим…');
    expect(login).toHaveBeenCalledOnce();
  });
});

describe('демо-доступ на форме входа', () => {
  it('рендерит три кнопки ролей и не предлагает админа', () => {
    render(<LoginForm onLogin={vi.fn()} />);
    const group = screen.getByRole('group', { name: 'Демо-доступ' });
    expect(group).toHaveTextContent('Учитель');
    expect(group).toHaveTextContent('Ученик');
    expect(group).toHaveTextContent('Родитель');
    expect(screen.queryByRole('button', { name: /админ/i })).toBeNull();
  });

  it('кнопка «Учитель» заполняет поля и входит демо-учёткой', async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    render(<LoginForm onLogin={login} />);
    await userEvent.click(screen.getByRole('button', { name: 'Учитель' }));
    expect(login).toHaveBeenCalledWith('teacher01@demo.og.test', 'DemoSchool2026!');
    expect(screen.getByLabelText('Email')).toHaveValue('teacher01@demo.og.test');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('кнопка «Родитель» входит родительской демо-учёткой', async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    render(<LoginForm onLogin={login} />);
    await userEvent.click(screen.getByRole('button', { name: 'Родитель' }));
    expect(login).toHaveBeenCalledWith('parent01@demo.og.test', 'DemoSchool2026!');
  });

  it('демо-кнопки блокируются, пока вход выполняется', async () => {
    const login = vi.fn(() => new Promise<void>(() => undefined));
    render(<LoginForm onLogin={login} />);
    const submit = screen.getByRole('button', { name: 'Войти' });
    await userEvent.click(screen.getByRole('button', { name: 'Ученик' }));
    expect(screen.getByRole('button', { name: 'Учитель' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Ученик' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Родитель' })).toBeDisabled();
    expect(submit).toBeDisabled();
    expect(submit).toHaveTextContent('Входим…');
    expect(login).toHaveBeenCalledOnce();
  });

  it('при 401 демо-входа показывает нейтральный текст, а не упрёк в опечатке', async () => {
    const login = vi
      .fn()
      .mockRejectedValue(new ApiError(401, 'invalid_credentials', 'Неверные учетные данные.'));
    render(<LoginForm onLogin={login} />);
    await userEvent.click(screen.getByRole('button', { name: 'Учитель' }));
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Демо-вход недоступен');
    expect(alert).not.toHaveTextContent('Email или пароль не подошли');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('при 429 демо-входа называет время повтора из Retry-After', async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError(429, 'rate_limit_exceeded', 'Too many attempts', undefined, 5 * 60_000),
      );
    render(<LoginForm onLogin={login} />);
    await userEvent.click(screen.getByRole('button', { name: 'Учитель' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Повторите через 5 мин.');
  });

  it('повторный клик демо-кнопки после ошибки снова подставляет пароль', async () => {
    const login = vi.fn().mockRejectedValueOnce(new Error('network'));
    render(<LoginForm onLogin={login} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ученик' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ученик' }));
    expect(login).toHaveBeenNthCalledWith(2, 'student01.1@demo.og.test', 'DemoSchool2026!');
  });
});
