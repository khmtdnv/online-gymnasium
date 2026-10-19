import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { Dialog } from '../app/components/ui/dialog';

it('диалог без Radix Trigger возвращает фокус на открывшую кнопку', async () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Открыть форму</button>
        <Dialog open={open} onOpenChange={setOpen} title="Форма" description="Проверка фокуса">
          <input aria-label="Данные" />
        </Dialog>
      </>
    );
  }
  render(<Example />);
  const trigger = screen.getByRole('button', { name: 'Открыть форму' });
  await userEvent.click(trigger);
  await userEvent.keyboard('{Escape}');
  await waitFor(() => expect(trigger).toHaveFocus());
});
