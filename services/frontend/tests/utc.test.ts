import { describe, expect, it } from 'vitest';
import { schoolPeriodsSchema } from '../app/features/schedule/school-periods';
import { matchPeriod, periodToUtc } from '../app/features/schedule/school-periods';

/** Контрактная сетка из спецификации: семь периодов школьного дня. */
const contract = schoolPeriodsSchema.parse({
  timezone: 'Asia/Yekaterinburg',
  effective_from: '2026-11-30',
  periods: [
    { number: 1, start_at: '09:00', end_at: '09:45' },
    { number: 2, start_at: '09:55', end_at: '10:40' },
    { number: 3, start_at: '11:00', end_at: '11:45' },
    { number: 4, start_at: '11:55', end_at: '12:40' },
    { number: 5, start_at: '13:00', end_at: '13:45' },
    { number: 6, start_at: '13:55', end_at: '14:40' },
    { number: 7, start_at: '15:00', end_at: '15:45' },
  ],
});

describe('время расписания', () => {
  it('переводит школьный период в UTC через сдвиг +05:00, независимо от зоны устройства', () => {
    const previous = process.env.TZ;
    process.env.TZ = 'Asia/Yekaterinburg';
    try {
      expect(periodToUtc('2026-11-30', contract.periods[0]).starts_at).toBe(
        '2026-11-30T04:00:00.000Z',
      );
      expect(periodToUtc('2026-11-30', contract.periods[0]).ends_at).toBe(
        '2026-11-30T04:45:00.000Z',
      );
      expect(periodToUtc('2026-11-30', contract.periods[6]).starts_at).toBe(
        '2026-11-30T10:00:00.000Z',
      );
      expect(periodToUtc('2026-11-30', contract.periods[6]).ends_at).toBe(
        '2026-11-30T10:45:00.000Z',
      );
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  });

  it('подбирает период только по точному совпадению границ в школьном времени', () => {
    expect(
      matchPeriod('2026-11-30T04:00:00Z', '2026-11-30T04:45:00Z', contract.periods)?.number,
    ).toBe(1);
    expect(
      matchPeriod('2026-11-30T10:00:00Z', '2026-11-30T10:45:00Z', contract.periods)?.number,
    ).toBe(7);
    expect(
      matchPeriod('2026-11-30T04:01:00Z', '2026-11-30T04:46:00Z', contract.periods),
    ).toBeUndefined();
    expect(
      matchPeriod('2026-11-30T04:00:00Z', '2026-11-30T04:50:00Z', contract.periods),
    ).toBeUndefined();
    expect(
      matchPeriod('2026-11-30T06:45:00Z', '2026-11-30T07:30:00Z', contract.periods),
    ).toBeUndefined();
  });

  it('принимает контракт семи периодов и отвергает искажённый', () => {
    expect(schoolPeriodsSchema.safeParse(contract).success).toBe(true);
    expect(schoolPeriodsSchema.safeParse({ ...contract, timezone: 'UTC' }).success).toBe(false);
    expect(
      schoolPeriodsSchema.safeParse({ ...contract, effective_from: '2026-11-30T00:00:00Z' })
        .success,
    ).toBe(false);
    expect(
      schoolPeriodsSchema.safeParse({
        ...contract,
        periods: [...contract.periods, { number: 8, start_at: '15:55', end_at: '16:40' }],
      }).success,
    ).toBe(false);
    expect(
      schoolPeriodsSchema.safeParse({
        ...contract,
        periods: [{ number: 1, start_at: '9:00', end_at: '09:45' }],
      }).success,
    ).toBe(false);
  });
});
