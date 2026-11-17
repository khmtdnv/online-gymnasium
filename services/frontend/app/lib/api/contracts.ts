import { z } from 'zod';

/** ID урока/класса/предмета числовой; пользователь Gateway определяется UUID. */
export const positiveIdSchema = z.number().int().positive().max(Number.MAX_SAFE_INTEGER);
export const roleSchema = z.enum(['student', 'teacher', 'parent', 'admin']);
export const instantSchema = z.iso.datetime({ offset: true });
export const daySchema = z.iso.date();
export const uuidSchema = z.uuid();

export const currentUserSchema = z.object({
  id: uuidSchema,
  email: z.email(),
  role: roleSchema,
});

export const tokenResponseSchema = z.object({ access_token: z.string().min(1) });

export const lessonSchema = z.object({
  id: positiveIdSchema,
  class_id: positiveIdSchema,
  teacher_id: uuidSchema,
  subject_id: positiveIdSchema,
  starts_at: instantSchema,
  ends_at: instantSchema,
  status: z.enum(['planned', 'canceled']),
  version: positiveIdSchema,
});

export const workloadSchema = z.object({
  class_id: positiveIdSchema,
  day: daySchema,
  planned_lessons_count: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  planned_minutes: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  // ClickHouse возвращает время UTC без offset; отображение добавит Z явно.
  refreshed_at: z.union([instantSchema, z.iso.datetime({ local: true })]),
});

export const documentStatusSchema = z.enum(['pending', 'processing', 'completed', 'failed']);
export const createdDocumentSchema = z.object({
  id: uuidSchema,
  document_type: z.enum(['certificate', 'contract', 'act', 'receipt']),
  status: documentStatusSchema,
});
export const documentJobSchema = createdDocumentSchema.extend({
  created_at: instantSchema,
  download_url: z.string().nullable().optional(),
});

export const apiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string(),
  }),
});

export type Role = z.infer<typeof roleSchema>;
export type CurrentUser = z.infer<typeof currentUserSchema>;
export type TokenResponse = z.infer<typeof tokenResponseSchema>;
export type Lesson = z.infer<typeof lessonSchema>;
export type ClassDailyWorkload = z.infer<typeof workloadSchema>;
export type CreatedDocument = z.infer<typeof createdDocumentSchema>;
export type DocumentJob = z.infer<typeof documentJobSchema>;
export type ApiErrorEnvelope = z.infer<typeof apiErrorEnvelopeSchema>;
