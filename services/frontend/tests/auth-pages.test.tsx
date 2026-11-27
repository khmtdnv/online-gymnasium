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
