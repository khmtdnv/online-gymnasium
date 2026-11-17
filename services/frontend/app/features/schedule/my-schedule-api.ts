import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { daySchema, lessonSchema, positiveIdSchema } from '../../lib/api/contracts';
import { teacherLessonSchema } from '../homework/api';
export const lessonCardSchema = lessonSchema.extend({
  class_name: z.string().min(1),
  subject_name: z.string().min(1),
  teacher_name: z.string().min(1),
});
export type LessonCardData = z.infer<typeof lessonCardSchema>;
const scheduleDaySchema = z.strictObject({
  date: daySchema,
  lessons: z.array(lessonCardSchema).max(1000),
});
export type ScheduleDay = z.infer<typeof scheduleDaySchema>;
const myScheduleSchema = z.strictObject({
  week_start: daySchema,
  timezone: z.literal('Asia/Yekaterinburg'),
  has_class: z.boolean(),
  days: z.array(scheduleDaySchema).length(6),
});
const lessonViewSchema = teacherLessonSchema.extend({
  lesson: lessonCardSchema,
  next_lesson: lessonCardSchema.nullable(),
});
export function createMyScheduleApi(client: ApiClient) {
  return {
    getMySchedule(weekStart: string, signal?: AbortSignal) {
      const query = new URLSearchParams({ week_start: daySchema.parse(weekStart) });
      return client.json(`/api/v1/my-schedule?${query}`, { signal }, myScheduleSchema);
    },
    getLessonView(lessonId: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/my-schedule/lessons/${positiveIdSchema.parse(lessonId)}`,
        { signal },
        lessonViewSchema,
      );
    },
  };
}
