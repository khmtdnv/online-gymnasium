import { describe, expect, it } from 'vitest';
import { isoToUtcInput, utcInputToIso } from '../app/features/schedule/utc';

describe('время расписания', () => {
  it('интерпретирует ввод как UTC, независимо от локальной зоны', () => {
    const previous = process.env.TZ;
    process.env.TZ = 'Asia/Yekaterinburg';
    try {
      expect(utcInputToIso('2026-10-03T09:00')).toBe('2026-10-03T09:00:00.000Z');
      expect(utcInputToIso('2026-10-03T00:01')).toBe('2026-10-03T00:01:00.000Z');
      expect(isoToUtcInput('2026-10-03T09:00:00+05:00')).toBe('2026-10-03T04:00');
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  });

  it.each(['2026-02-30T09:00', '2026-13-01T09:00', '2026-10-03T25:00', 'bad'])(
    'не нормализует недопустимый ввод %s',
    (value) => {
      expect(() => utcInputToIso(value)).toThrow();
    },
  );
});
