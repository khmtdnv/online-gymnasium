import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { daySchema, instantSchema, uuidSchema } from '../../lib/api/contracts';

const positiveId = z.number().int().min(1).max(2147483647);

export const attendanceStatusSchema = z.enum([
  'present',
  'absent_sick',
  'absent_excused',
  'absent_unexcused',
]);
export type AttendanceStatus = z.infer<typeof attendanceStatusSchema>;

export const gradeKindSchema = z.enum(['oral', 'written', 'control']);
export type GradeKind = z.infer<typeof gradeKindSchema>;

const subjectAverageSchema = z.strictObject({
  subject_id: positiveId,
  average: z.number().min(2).max(5),
  grade_count: z.number().int().min(1),
  quarter_grade: z.number().int().min(2).max(5),
});
export type SubjectAverage = z.infer<typeof subjectAverageSchema>;

const diarySummarySchema = z.strictObject({
  quarter: z.number().int().min(1).max(4),
  quarter_from: daySchema,
  quarter_to: daySchema,
  subject_averages: z.array(subjectAverageSchema),
  absences: z.array(
    z.strictObject({
      lesson_id: positiveId,
      lesson_date: daySchema,
      reason: z.enum(['sick', 'excused', 'unexcused']),
    }),
  ),
});
export type DiarySummary = z.infer<typeof diarySummarySchema>;

const diaryLessonSlotSchema = z.strictObject({
  lesson_id: positiveId,
  subject_id: positiveId,
  date: daySchema,
  starts_at: instantSchema,
  ends_at: instantSchema,
  status: z.enum(['planned', 'canceled']),
  attendance: z.enum(['present', 'absent', 'unmarked']),
  absence_reason: z.enum(['sick', 'excused', 'unexcused']).nullable(),
  grades: z.array(z.tuple([z.number().int().min(2).max(5), gradeKindSchema])),
  homework_status: z
    .enum(['submitted', 'returned', 'graded', 'not_submitted'])
    .nullable(),
  homework_grade: z.number().int().min(2).max(5).nullable(),
});
export type DiaryLessonSlot = z.infer<typeof diaryLessonSlotSchema>;

const diaryWeekSchema = z.strictObject({
  week_start: daySchema,
  timezone: z.literal('Asia/Yekaterinburg'),
  demo_cutoff: daySchema.nullable(),
  quarter: z.number().int().min(1).max(4),
  lessons: z.array(diaryLessonSlotSchema),
  summary: diarySummarySchema,
});
export type DiaryWeek = z.infer<typeof diaryWeekSchema>;

/** Записи урока в ответе POST/GET `/lessons/{id}/entries` (упрощённые строки). */
const lessonRecordAttendanceSchema = z.strictObject({
  lesson_id: positiveId,
  student_id: uuidSchema,
  status: attendanceStatusSchema,
});

const lessonRecordGradeSchema = z.strictObject({
  lesson_id: positiveId,
  student_id: uuidSchema,
  grade: z.number().int().min(2).max(5),
  kind: gradeKindSchema,
});

const lessonRecordResultSchema = z.strictObject({
  attendance: z.array(lessonRecordAttendanceSchema),
  grades: z.array(lessonRecordGradeSchema),
});
export type LessonRecordResult = z.infer<typeof lessonRecordResultSchema>;

export type DiaryApi = ReturnType<typeof createDiaryApi>;

export interface RecordLessonEntriesInput {
  lesson_id: number;
  context: {
    class_id: number;
    subject_id: number;
    lesson_date: string;
    status: 'planned';
    teacher_id: string;
  };
  attendance: Array<{ student_id: string; status: AttendanceStatus }>;
  grades: Array<{
    student_id: string;
    kind: GradeKind;
    grade: number;
  }>;
}

/** Строит query-строку дневника: `week_start` и `student_id` по необходимости. */
function diaryParams(weekStart?: string, studentId?: string) {
  const params = new URLSearchParams();
  if (weekStart) params.set('week_start', daySchema.parse(weekStart));
  if (studentId) params.set('student_id', uuidSchema.parse(studentId));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export function createDiaryApi(client: ApiClient) {
  return {
    getDiaryWeek(
      weekStart: string | undefined,
      studentId: string | undefined,
      signal?: AbortSignal,
    ) {
      return client.json(
        `/api/v1/diary${diaryParams(weekStart, studentId)}`,
        { signal },
        diaryWeekSchema,
      );
    },
    getDiarySummary(
      quarter: number,
      studentId: string | undefined,
      signal?: AbortSignal,
    ) {
      const params = new URLSearchParams({ quarter: String(quarter) });
      if (studentId) params.set('student_id', uuidSchema.parse(studentId));
      return client.json(`/api/v1/diary/summary?${params}`, { signal }, diarySummarySchema);
    },
    recordLessonEntries(input: RecordLessonEntriesInput) {
      return client.json(
        `/api/v1/lessons/${positiveId.parse(input.lesson_id)}/entries`,
        {
          method: 'POST',
          // lesson_id живёт в адресе; тело повторяет контракт Gateway без него.
          body: JSON.stringify({
            context: input.context,
            attendance: input.attendance,
            grades: input.grades,
          }),
        },
        lessonRecordResultSchema,
      );
    },
    getLessonEntries(lessonId: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/lessons/${positiveId.parse(lessonId)}/entries`,
        { signal },
        lessonRecordResultSchema,
      );
    },
  };
}
