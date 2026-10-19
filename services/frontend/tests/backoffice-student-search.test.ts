import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const source = readFileSync(
  resolve(
    import.meta.dirname,
    '../../backoffice/src/backoffice_admin/static/backoffice_admin/student_search.js',
  ),
  'utf8',
);
const student = {
  id: 'aaaaaaaa-0000-4000-8000-000000000001',
  label: 'Петров Иван Сергеевич · student@example.test',
};
let cleanupListeners: (() => void) | undefined;
let input: HTMLInputElement;
let hidden: HTMLInputElement;
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  const listeners = vi.spyOn(document, 'addEventListener');
  cleanupListeners = () => {
    for (const [type, listener, options] of listeners.mock.calls)
      document.removeEventListener(type, listener, options);
    listeners.mockRestore();
  };
  document.body.innerHTML = `<form id="student-class-form" data-search-url="/admin/users/search/">
    <input id="id_student_id"><input id="student-label">
    <div id="student-picker"><input id="student-search" role="combobox" aria-expanded="false" aria-controls="student-results" required>
    <button type="button" id="clear-student" hidden>Очистить</button>
    <ul id="student-results" role="listbox" hidden></ul></div>
    <p id="student-search-status" role="status"></p><button>Отправить</button></form>`;
  fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ results: [student] })));
  vi.stubGlobal('fetch', fetcher);
  input = document.querySelector('#student-search')!;
  hidden = document.querySelector('#id_student_id')!;
  window.eval(source);
  input.focus();
});

afterEach(() => {
  cleanupListeners?.();
  vi.clearAllTimers();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
  vi.useRealTimers();
});

async function type(value: string) {
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await vi.advanceTimersByTimeAsync(300);
}

function key(value: string) {
  input.dispatchEvent(
    new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }),
  );
}

function list() {
  return document.querySelector<HTMLElement>('#student-results')!;
}

it('shows results directly under the same input after debounce', async () => {
  await type('Петр');
  expect(list().hidden).toBe(false);
  expect(list().querySelector('[role="option"]')?.textContent).toBe(student.label);
  expect(input.getAttribute('aria-expanded')).toBe('true');
  expect(hidden.value).toBe('');
});

it('selects by arrows and Enter without submitting the form', async () => {
  await type('Петр');
  key('ArrowDown');
  expect(input.getAttribute('aria-activedescendant')).toBe(list().firstElementChild?.id);
  key('Enter');
  expect(input.value).toBe(student.label);
  expect(hidden.value).toBe(student.id);
  expect(list().hidden).toBe(true);
  expect(input.validationMessage).toBe('');
});

it('selects by mouse and clears both display and UUID', async () => {
  await type('Петр');
  list().querySelector<HTMLElement>('[role="option"]')!.click();
  expect(hidden.value).toBe(student.id);
  document.querySelector<HTMLButtonElement>('#clear-student')!.click();
  expect(input.value).toBe('');
  expect(hidden.value).toBe('');
  expect(list().hidden).toBe(true);
  expect(input.validationMessage).not.toBe('');
});

it('Escape closes without selecting the highlighted suggestion', async () => {
  await type('Петр');
  key('ArrowDown');
  key('Escape');
  expect(list().hidden).toBe(true);
  expect(input.getAttribute('aria-expanded')).toBe('false');
  expect(input.hasAttribute('aria-activedescendant')).toBe(false);
  expect(hidden.value).toBe('');
  expect(input.value).toBe('Петр');
});

it('editing a selected label immediately invalidates its old UUID', async () => {
  await type('Петр');
  key('ArrowDown');
  key('Enter');
  input.value = 'Другой';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  expect(hidden.value).toBe('');
  expect(input.validationMessage).not.toBe('');
});

it('late old response cannot overwrite a newer result', async () => {
  let finishOld!: (response: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOld = resolve;
      }),
  );
  await type('старый');
  await type('Петр');
  finishOld(new Response(JSON.stringify({ results: [{ ...student, label: 'Старый ответ' }] })));
  await vi.advanceTimersByTimeAsync(0);
  expect(list().textContent).toBe(student.label);
});

it('focus leaving the widget prevents a pending response from reopening it', async () => {
  let finish!: (response: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await type('Петр');
  input.blur();
  finish(new Response(JSON.stringify({ results: [student] })));
  await vi.advanceTimersByTimeAsync(0);
  expect(list().hidden).toBe(true);
});

it('renders upstream labels as text, never HTML', async () => {
  fetcher.mockResolvedValueOnce(
    new Response(
      JSON.stringify({ results: [{ ...student, label: '<img src=x onerror=alert(1)>' }] }),
    ),
  );
  await type('Петр');
  expect(list().querySelector('img')).toBeNull();
  expect(list().textContent).toBe('<img src=x onerror=alert(1)>');
});

it('does not search below two characters or accept free text as selection', async () => {
  await type('П');
  expect(fetcher).not.toHaveBeenCalled();
  expect(hidden.value).toBe('');
  expect(input.checkValidity()).toBe(false);
});

it('reports empty and failed searches without retaining stale options', async () => {
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ results: [] })));
  await type('никто');
  expect(list().hidden).toBe(true);
  expect(document.querySelector('#student-search-status')?.textContent).toContain('не найдены');
  fetcher.mockRejectedValueOnce(new Error('offline'));
  await type('Петр');
  expect(hidden.value).toBe('');
  expect(document.querySelector('#student-search-status')?.textContent).toContain('недоступен');
});
