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

  it('показывает монограмму, роль и слот уведомлений в шапке', () => {
    render(
      <MemoryRouter>
        <AppShell
          user={{ ...user, first_name: 'Мария', last_name: 'Соколова' }}
          onLogout={vi.fn()}
          notificationControl={<button type="button">bell-stub</button>}
        >
          <h1>Главная</h1>
        </AppShell>
      </MemoryRouter>,
    );
    expect(screen.getByText('МС')).toBeInTheDocument();
    expect(screen.getByText('Администратор')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'bell-stub' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Профиль' }).length).toBeGreaterThan(0);
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
