import { z } from 'zod';
import { daySchema } from '../../lib/api/contracts';
import { schoolTime, schoolTimezone } from './school-dates';

/** HH:MM местного школьного времени без даты — формат контракта Schedule. */
const hhMmSchema = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, 'HH:MM');

export const schoolPeriodSchema = z.strictObject({
  number: z.number().int().min(1).max(7),
  start_at: hhMmSchema,
  end_at: hhMmSchema,
});
export const schoolPeriodsSchema = z.strictObject({
  timezone: z.literal(schoolTimezone),
  effective_from: daySchema,
  periods: z.array(schoolPeriodSchema),
});
export type SchoolPeriod = z.infer<typeof schoolPeriodSchema>;
export type SchoolPeriods = z.infer<typeof schoolPeriodsSchema>;

/**
 * Период урока — только при точном совпадении начала и конца
 * с границами периода в школьном местном времени.
 */
export function matchPeriod(
  startsAt: string,
  endsAt: string,
  periods: SchoolPeriod[],
): SchoolPeriod | undefined {
  const start = schoolTime(startsAt);
  const end = schoolTime(endsAt);
  return periods.find((period) => period.start_at === start && period.end_at === end);
}

/** Фиксированный сдвиг зоны школы (Asia/Yekaterinburg, без DST) для сбора UTC. */
const SCHOOL_UTC_OFFSET = '+05:00';

/** Школьная дата + период → границы урока в UTC; время не вводится вручную. */
export function periodToUtc(
  day: string,
  period: SchoolPeriod,
): { starts_at: string; ends_at: string } {
  return {
    starts_at: new Date(`${day}T${period.start_at}:00${SCHOOL_UTC_OFFSET}`).toISOString(),
    ends_at: new Date(`${day}T${period.end_at}:00${SCHOOL_UTC_OFFSET}`).toISOString(),
  };
}

/** Раскладка уроков дня по периодам сетки; остальное — «вне сетки». */
export function splitByPeriods<T extends { starts_at: string; ends_at: string }>(
  lessons: T[],
  periods: SchoolPeriod[],
): { byPeriod: Map<number, T[]>; offGrid: T[] } {
  const byPeriod = new Map<number, T[]>();
  const offGrid: T[] = [];
  for (const lesson of lessons) {
    const period = matchPeriod(lesson.starts_at, lesson.ends_at, periods);
    if (!period) {
      offGrid.push(lesson);
      continue;
    }
    const slot = byPeriod.get(period.number);
    if (slot) slot.push(lesson);
    else byPeriod.set(period.number, [lesson]);
  }
  return { byPeriod, offGrid };
}
