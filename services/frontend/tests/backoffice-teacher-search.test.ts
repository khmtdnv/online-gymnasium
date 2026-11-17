import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';

const source = readFileSync(
  resolve(
    import.meta.dirname,
    '../../backoffice/src/backoffice_admin/static/backoffice_admin/student_search.js',
  ),
  'utf8',
);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

it('teacher picker uses its own URL and UUID field, not student defaults', async () => {
  vi.useFakeTimers();
  document.body.innerHTML = `<form id="student-class-form" data-search-url="/admin/teachers/search/" data-id-field="id_teacher_id" data-user-kind="teacher">
    <input id="id_teacher_id"><input id="student-label">
    <div id="student-picker"><input id="student-search" required>
    <button id="clear-student" type="button"></button><ul id="student-results" hidden></ul></div>
    <p id="student-search-status"></p></form>`;
  const teacher = {
    id: '8df96b7a-7d30-44e7-b577-f6581300e101',
    label: 'Петров Иван · teacher@example.test',
  };
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ results: [teacher] })));
  vi.stubGlobal('fetch', fetcher);
  const listenerSpy = vi.spyOn(document, 'addEventListener');
  try {
    window.eval(source);
    const input = document.querySelector<HTMLInputElement>('#student-search')!;
    input.focus();
    input.value = 'Петр';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(new URL(String(fetcher.mock.calls[0][0])).pathname).toBe('/admin/teachers/search/');
    document.querySelector<HTMLElement>('[role="option"]')!.click();
    expect(document.querySelector<HTMLInputElement>('#id_teacher_id')!.value).toBe(teacher.id);
    expect(input.checkValidity()).toBe(true);
    expect(document.querySelector('#student-search-status')!.textContent).toContain(
      'Выбран преподаватель',
    );
  } finally {
    for (const [type, listener, options] of listenerSpy.mock.calls)
      document.removeEventListener(type, listener, options);
    listenerSpy.mockRestore();
  }
});
