import { describe, expect, it } from 'vitest';
import {
  currentUserSchema,
  documentJobSchema,
  lessonSchema,
  workloadSchema,
} from '../app/lib/api/contracts';

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
