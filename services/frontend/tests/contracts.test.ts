import { describe, expect, it } from 'vitest';
import {
  currentUserSchema,
  documentJobSchema,
  lessonSchema,
  workloadSchema,
} from '../app/lib/api/contracts';
import { directorySchema } from '../app/features/schedule/api';
import { myScheduleSchema } from '../app/features/schedule/my-schedule-api';
import { schoolPeriodsSchema } from '../app/features/schedule/school-periods';

const id = '6c6f3434-e4cc-4619-8c2a-8d733913ecda';
const lesson = {
  id: 501,
  class_id: 9021,
  teacher_id: id,
  subject_id: 1000,
  starts_at: '2026-10-05T09:00:00Z',
  ends_at: '2026-10-05T09:45:00Z',
  status: 'planned',
  version: 1,
};

describe('внешние контракты', () => {
  it('принимает UUID учителя, а не старый числовой ID', () => {
    expect(lessonSchema.safeParse(lesson).success).toBe(true);
    expect(lessonSchema.safeParse({ ...lesson, teacher_id: 100 }).success).toBe(false);
  });
  it('проверяет UUID и известную роль пользователя', () => {
    const user = { id, email: 'admin@school.ru', role: 'admin' };
    expect(currentUserSchema.safeParse(user).success).toBe(true);
    expect(currentUserSchema.safeParse({ ...user, id: 'broken' }).success).toBe(false);
    expect(currentUserSchema.safeParse({ ...user, role: 'root' }).success).toBe(false);
  });

  it('отклоняет числовые ID, которые JavaScript не может точно представить', () => {
    expect(lessonSchema.safeParse(lesson).success).toBe(true);
    expect(lessonSchema.safeParse({ ...lesson, id: 9007199254740992 }).success).toBe(false);
    expect(lessonSchema.safeParse({ ...lesson, version: 0 }).success).toBe(false);
  });

  it('не принимает неизвестное состояние документа', () => {
    const job = {
      id,
      document_type: 'certificate',
      status: 'completed',
      created_at: '2026-10-03T09:00:00Z',
    };
    expect(documentJobSchema.safeParse(job).success).toBe(true);
    expect(documentJobSchema.safeParse({ ...job, status: 'unknown' }).success).toBe(false);
  });

  it('принимает UTC-время ClickHouse без offset и отвергает отрицательную нагрузку', () => {
    const workload = {
      class_id: 9021,
      day: '2026-10-05',
      planned_lessons_count: 3,
      planned_minutes: 135,
      refreshed_at: '2026-10-03T09:00:00',
    };
    expect(workloadSchema.safeParse(workload).success).toBe(true);
    expect(workloadSchema.safeParse({ ...workload, planned_minutes: -1 }).success).toBe(false);
  });
});

describe('контракт семи периодов', () => {
  const periods = [
    { number: 1, start_at: '09:00', end_at: '09:45' },
    { number: 2, start_at: '09:55', end_at: '10:40' },
    { number: 3, start_at: '11:00', end_at: '11:45' },
    { number: 4, start_at: '11:55', end_at: '12:40' },
    { number: 5, start_at: '13:00', end_at: '13:45' },
    { number: 6, start_at: '13:55', end_at: '14:40' },
    { number: 7, start_at: '15:00', end_at: '15:45' },
  ];

  it('принимает подтверждённую сетку и отвергает восьмой номер и не-HH:MM время', () => {
    const contract = {
      timezone: 'Asia/Yekaterinburg',
      effective_from: '2026-11-30',
      periods,
    };
    expect(schoolPeriodsSchema.safeParse(contract).success).toBe(true);
    expect(schoolPeriodsSchema.safeParse({ ...contract, timezone: 'Europe/Moscow' }).success).toBe(
      false,
    );
    expect(
      schoolPeriodsSchema.safeParse({ ...contract, effective_from: '30.11.2026' }).success,
    ).toBe(false);
    expect(
      schoolPeriodsSchema.safeParse({
        ...contract,
        periods: [...periods, { number: 8, start_at: '15:55', end_at: '16:40' }],
      }).success,
    ).toBe(false);
    expect(
      schoolPeriodsSchema.safeParse({
        ...contract,
        periods: periods.map((item) => (item.number === 1 ? { ...item, start_at: '0900' } : item)),
      }).success,
    ).toBe(false);
  });

  it('требует периоды в ответе my-schedule', () => {
    const payload = {
      week_start: '2026-10-05',
      timezone: 'Asia/Yekaterinburg',
      has_class: true,
      days: Array.from({ length: 6 }, (_, index) => ({
        date: `2026-10-${String(5 + index).padStart(2, '0')}`,
        lessons: [],
      })),
      periods,
    };
    expect(myScheduleSchema.safeParse(payload).success).toBe(true);
    const withoutPeriods: Record<string, unknown> = { ...payload };
    delete withoutPeriods.periods;
    expect(myScheduleSchema.safeParse(withoutPeriods).success).toBe(false);
  });

  it('разбирает периоды в справочнике directory', () => {
    const directory = {
      classes: [{ id: 9021, name: '9А' }],
      subjects: [{ id: 1000, name: 'Математика' }],
      periods,
    };
    expect(directorySchema.safeParse(directory).success).toBe(true);
    expect(directorySchema.safeParse({ ...directory, periods: '7' }).success).toBe(false);
  });
});
