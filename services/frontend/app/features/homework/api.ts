import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { daySchema, instantSchema, lessonSchema, uuidSchema } from '../../lib/api/contracts';

const id = z.number().int().min(1).max(2147483647);
export const homeworkFileSchema = z.strictObject({
  id,
  homework_id: id,
  file_name: z.string().min(1).max(255),
  size_bytes: z.number().int().min(1).max(10485760),
  content_type: z.string().min(1),
  upload_status: z.enum(['pending', 'ready']),
});
export type HomeworkFile = z.infer<typeof homeworkFileSchema>;
export const homeworkSchema = z.strictObject({
  id,
  issued_lesson_id: id,
  class_id: id,
  subject_id: id,
  author_id: uuidSchema,
  description: z.string().min(1).max(10000),
  due_lesson_id: id.nullable(),
  manual_due_datetime: instantSchema.nullable(),
  created_at: instantSchema,
  files: z.array(homeworkFileSchema).max(5).default([]),
});
export const studentHomeworkSchema = homeworkSchema.extend({
  final_due_datetime: instantSchema.nullable(),
  due_status: z.enum(['manual', 'lesson', 'lesson_cancelled']),
});
export type Homework = z.infer<typeof homeworkSchema>;
export type StudentHomework = z.infer<typeof studentHomeworkSchema>;
export const homeworkListItemSchema = studentHomeworkSchema.extend({
  subject_name: z.string().min(1),
  teacher_name: z.string().min(1),
  latest_answer_status: z.enum(['submitted', 'returned', 'graded']).nullable(),
  grade: z.number().int().min(2).max(5).nullable(),
});
export type HomeworkListItem = z.infer<typeof homeworkListItemSchema>;
export type HomeworkState = 'all' | 'needs_action' | 'submitted' | 'returned' | 'graded';
const homeworkPageSchema = z.strictObject({
  date_from: daySchema,
  date_to: daySchema,
  timezone: z.literal('Asia/Yekaterinburg'),
  total: z.number().int().min(0).max(1000),
  items: z.array(homeworkListItemSchema).max(100),
});
export const teacherLessonSchema = z.strictObject({
  lesson: lessonSchema,
  next_lesson: lessonSchema.nullable(),
  homework_for_lesson: z.array(studentHomeworkSchema),
  homework_from_lesson: z.array(studentHomeworkSchema),
});
export type TeacherLesson = z.infer<typeof teacherLessonSchema>;
export interface HomeworkFileInput {
  file_name: string;
  size_bytes: number;
  content_type: string;
  content_sha256: string;
}
export interface CreateHomeworkInput {
  description: string;
  due_lesson_id?: number;
  manual_due_datetime?: string;
  files: HomeworkFileInput[];
}

export const homeworkAnswerFileSchema = homeworkFileSchema
  .omit({ homework_id: true })
  .extend({ answer_id: id });
export type HomeworkAnswerFile = z.infer<typeof homeworkAnswerFileSchema>;
export const homeworkAnswerSchema = z.strictObject({
  id,
  homework_id: id,
  student_id: uuidSchema,
  student_name: z.string(),
  attempt_number: id,
  answer_text: z.string().max(10000),
  status: z.enum(['submitted', 'returned', 'graded']),
  submitted_at: instantSchema,
  grade: z.number().int().min(2).max(5).nullable(),
  teacher_comment: z.string().max(10000),
  reviewer_id: uuidSchema.nullable(),
  reviewed_at: instantSchema.nullable(),
  files: z.array(homeworkAnswerFileSchema).max(5),
});
export type HomeworkAnswer = z.infer<typeof homeworkAnswerSchema>;
export interface SubmitHomeworkAnswerInput {
  answer_text: string;
  files: HomeworkFileInput[];
}
export interface ReviewHomeworkAnswerInput {
  status: 'returned' | 'graded';
  grade: number | null;
  teacher_comment: string;
}

export const teacherReviewPageSchema = z.object({
  items: z.array(
    z.object({
      answer_id: id,
      homework_id: id,
      lesson_id: id,
      class_id: id,
      subject_id: id,
      class_name: z.string(),
      subject_name: z.string(),
      student_id: uuidSchema,
      student_name: z.string(),
      description: z.string(),
      status: z.enum(['submitted', 'returned', 'graded']),
      submitted_at: instantSchema,
    }),
  ),
  next_cursor: z.number().int().positive().nullable(),
});

export function createHomeworkApi(client: ApiClient) {
  return {
    listTeacherReviews(cursor: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/homework/review-queue?cursor=${cursor}`,
        { signal },
        teacherReviewPageSchema,
      );
    },
    getAnswer(homeworkId: number, answerId: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/homework/${id.parse(homeworkId)}/answers/${id.parse(answerId)}`,
        { signal },
        homeworkAnswerSchema,
      );
    },
    listMyHomework(
      dateFrom: string,
      dateTo: string,
      state: HomeworkState,
      offset = 0,
      signal?: AbortSignal,
    ) {
      const query = new URLSearchParams({
        date_from: daySchema.parse(dateFrom),
        date_to: daySchema.parse(dateTo),
        state,
        limit: '50',
        offset: String(offset),
      });
      return client.json(`/api/v1/my-homework?${query}`, { signal }, homeworkPageSchema);
    },
    listAnswers(
      homeworkId: number,
      options: { studentId?: string; offset?: number } = {},
      signal?: AbortSignal,
    ) {
      const query = new URLSearchParams({ limit: '50', offset: String(options.offset ?? 0) });
      if (options.studentId) query.set('student_id', uuidSchema.parse(options.studentId));
      return client.json(
        `/api/v1/homework/${id.parse(homeworkId)}/answers?${query}`,
        { signal },
        z.array(homeworkAnswerSchema),
      );
    },
    submitAnswer(
      homeworkId: number,
      key: string,
      input: SubmitHomeworkAnswerInput,
      signal?: AbortSignal,
    ) {
      return client.json(
        `/api/v1/homework/${id.parse(homeworkId)}/answers`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': key },
          body: JSON.stringify(input),
          signal,
        },
        homeworkAnswerSchema,
      );
    },
    reviewAnswer(
      homeworkId: number,
      answerId: number,
      input: ReviewHomeworkAnswerInput,
      signal?: AbortSignal,
    ) {
      return client.json(
        `/api/v1/homework/${id.parse(homeworkId)}/answers/${id.parse(answerId)}/review`,
        { method: 'PUT', body: JSON.stringify(input), signal },
        homeworkAnswerSchema,
      );
    },
    uploadAnswerFile(
      homeworkId: number,
      file: HomeworkAnswerFile,
      selected: File,
      signal?: AbortSignal,
    ) {
      const body = new FormData();
      body.append('file', selected);
      return client
        .json(
          `/api/v1/homework/${id.parse(homeworkId)}/answers/${id.parse(file.answer_id)}/files/${id.parse(file.id)}`,
          { method: 'PUT', body, signal },
          homeworkAnswerFileSchema,
        )
        .then((result) => {
          if (
            result.id !== file.id ||
            result.answer_id !== file.answer_id ||
            result.file_name !== file.file_name ||
            result.size_bytes !== file.size_bytes ||
            result.content_type !== file.content_type ||
            result.upload_status !== 'ready'
          )
            throw new Error('Неверный ответ загрузки файла.');
          return result;
        });
    },
    downloadAnswerFile(homeworkId: number, file: HomeworkAnswerFile, signal?: AbortSignal) {
      return client.downloadHomeworkFile(
        `/api/v1/homework/${id.parse(homeworkId)}/answers/${id.parse(file.answer_id)}/files/${id.parse(file.id)}`,
        file,
        signal,
      );
    },
    listLessons(dateFrom: string, dateTo: string, signal?: AbortSignal) {
      const query = new URLSearchParams({
        date_from: daySchema.parse(dateFrom),
        date_to: daySchema.parse(dateTo),
      });
      return client.json(`/api/v1/lessons?${query}`, { signal }, z.array(lessonSchema));
    },
    getTeacherLesson(lessonId: number, signal?: AbortSignal) {
      return client.json(`/api/v1/lessons/${id.parse(lessonId)}`, { signal }, teacherLessonSchema);
    },
    createHomework(lessonId: number, input: CreateHomeworkInput, signal?: AbortSignal) {
      return client.json(
        `/api/v1/lessons/${id.parse(lessonId)}/homework`,
        { method: 'POST', body: JSON.stringify(input), signal },
        homeworkSchema,
      );
    },
    uploadHomeworkFile(file: HomeworkFile, selected: File, signal?: AbortSignal) {
      const body = new FormData();
      body.append('file', selected);
      return client
        .json(
          `/api/v1/homework/${id.parse(file.homework_id)}/files/${id.parse(file.id)}`,
          { method: 'PUT', body, signal },
          homeworkFileSchema,
        )
        .then((result) => {
          if (
            result.id !== file.id ||
            result.homework_id !== file.homework_id ||
            result.file_name !== file.file_name ||
            result.size_bytes !== file.size_bytes ||
            result.content_type !== file.content_type ||
            result.upload_status !== 'ready'
          )
            throw new Error('Неверный ответ загрузки файла.');
          return result;
        });
    },
    listHomework(offset = 0, signal?: AbortSignal) {
      const query = new URLSearchParams({
        limit: '50',
        offset: String(z.number().int().min(0).max(2147483647).parse(offset)),
      });
      return client.json(`/api/v1/homework?${query}`, { signal }, z.array(studentHomeworkSchema));
    },
    getHomework(homeworkId: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/homework/${id.parse(homeworkId)}`,
        { signal },
        studentHomeworkSchema,
      );
    },
    downloadHomeworkFile(file: HomeworkFile, signal?: AbortSignal) {
      return client.downloadHomeworkFile(
        `/api/v1/homework/${id.parse(file.homework_id)}/files/${id.parse(file.id)}`,
        file,
        signal,
      );
    },
  };
}
export type HomeworkApi = ReturnType<typeof createHomeworkApi>;
