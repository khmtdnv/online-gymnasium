import { describe, expect, it } from 'vitest';
import { displayHomeworkDescription } from '../app/features/homework/display-description';

describe('отображение учебных заданий', () => {
  it('заменяет только известный демонстрационный текст', () => {
    expect(
      displayHomeworkDescription(
        '[ДЕМО] Можно выполнить: ответа пока нет. Прочитайте условие и объясните решение.',
      ),
    ).toBe('Прочитайте условие и объясните решение.');
  });
  it('сохраняет произвольное описание преподавателя', () => {
    const original = '[ДЕМО] Создайте демонстрацию решения.';
    expect(displayHomeworkDescription(original)).toBe(original);
  });
});
