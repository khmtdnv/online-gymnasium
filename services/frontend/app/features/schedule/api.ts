import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { createMyScheduleApi } from './my-schedule-api';
import {
  daySchema,
  instantSchema,
  lessonSchema,
  positiveIdSchema,
  uuidSchema,
} from '../../lib/api/contracts';

export const intervalSchema = z
  .object({ starts_at: instantSchema, ends_at: instantSchema })
  .superRefine((value, context) => {
    if (Date.parse(value.ends_at) <= Date.parse(value.starts_at))
      context.addIssue({
        code: 'custom',
        message: 'Конец урока должен быть позже начала.',
        path: ['ends_at'],
      });
    if (
      new Date(value.starts_at).toISOString().slice(0, 10) !==
      new Date(value.ends_at).toISOString().slice(0, 10)
    )
      context.addIssue({
        code: 'custom',
        message: 'Урок должен начинаться и заканчиваться в один день UTC.',
        path: ['ends_at'],
      });
  });
export const createLessonInputSchema = intervalSchema.safeExtend({
  class_id: positiveIdSchema,
  teacher_id: uuidSchema,
  subject_id: positiveIdSchema,
});
export const updateLessonInputSchema = intervalSchema.safeExtend({
  expected_version: positiveIdSchema,
});
export type CreateLessonInput = z.infer<typeof createLessonInputSchema>;
export type UpdateLessonInput = z.infer<typeof updateLessonInputSchema>;

export function createScheduleApi(client: ApiClient) {
  return {
    ...createMyScheduleApi(client),
    listLessons(classId: number, day: string, signal?: AbortSignal) {
      const query = new URLSearchParams({
        class_id: String(positiveIdSchema.parse(classId)),
        date: daySchema.parse(day),
      });
      return client.json(`/api/v1/schedule/lessons?${query}`, { signal }, z.array(lessonSchema));
    },
    createLesson(input: CreateLessonInput, idempotencyKey: string) {
      return client.json(
        '/api/v1/schedule/lessons',
        {
          method: 'POST',
          headers: { 'Idempotency-Key': z.string().min(1).parse(idempotencyKey) },
          body: JSON.stringify(createLessonInputSchema.parse(input)),
        },
        lessonSchema,
      );
    },
    updateLesson(id: number, input: UpdateLessonInput) {
      return client.json(
        `/api/v1/schedule/lessons/${positiveIdSchema.parse(id)}`,
        { method: 'PATCH', body: JSON.stringify(updateLessonInputSchema.parse(input)) },
        lessonSchema,
      );
    },
    cancelLesson(id: number, expectedVersion: number) {
      return client.json(
        `/api/v1/schedule/lessons/${positiveIdSchema.parse(id)}/cancel`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: positiveIdSchema.parse(expectedVersion) }),
        },
        lessonSchema,
      );
    },
  };
}
