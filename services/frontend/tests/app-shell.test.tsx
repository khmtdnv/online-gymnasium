import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from '../app/components/app-shell';
import { AsyncState } from '../app/components/async-state';
import type { CurrentUser } from '../app/lib/api/contracts';

const user: CurrentUser = {
  id: '6c6f3434-e4cc-4619-8c2a-8d733913ecda',
  email: 'admin@school.ru',
  role: 'admin',
};

function shell(currentUser = user) {
  return render(
    <MemoryRouter>
      <AppShell user={currentUser} onLogout={vi.fn()}>
        <h1>Главная</h1>
      </AppShell>
    </MemoryRouter>,
  );
}

describe('оболочка', () => {
  it('показывает административные разделы и отдельный вход Django', () => {
    shell();
    expect(screen.getByRole('link', { name: 'Расписание' })).toHaveAttribute('href', '/schedule');
    expect(screen.getByRole('link', { name: /администрирование/i })).toHaveAttribute(
      'href',
      '/admin/',
    );
  });

  it('не предлагает ученику чужое расписание или справки', () => {
    shell({ ...user, role: 'student' });
    expect(screen.queryByRole('link', { name: 'Расписание' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Справки' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Профиль' }).length).toBeGreaterThan(0);
  });

  it('закрывает мобильное меню по Escape и возвращает фокус', async () => {
    const keyboard = userEvent.setup();
    shell();
    const trigger = screen.getByRole('button', { name: 'Открыть меню' });
    trigger.focus();
    await keyboard.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'Навигация' })).toBeInTheDocument();
    await keyboard.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('показывает request ID и доступную кнопку повторного чтения', async () => {
    const retry = vi.fn();
    render(
      <AsyncState
        state="error"
        title="Не удалось загрузить"
        requestId="request-123"
        onRetry={retry}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('request-123');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
