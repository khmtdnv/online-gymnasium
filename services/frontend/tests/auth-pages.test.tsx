import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LoginForm } from '../app/features/auth/login-form';

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
});
