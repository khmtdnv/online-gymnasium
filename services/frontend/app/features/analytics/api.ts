import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { daySchema, positiveIdSchema, uuidSchema } from '../../lib/api/contracts';

const progressRow = z.strictObject({
  student_id: uuidSchema,
  subject_id: positiveIdSchema,
  student_name: z.string().min(1),
  subject_name: z.string().min(1),
  graded_count: z.number().int().positive(),
  average_grade: z.number().min(2).max(5),
});
export type ProgressRow = z.infer<typeof progressRow>;
const auditEvent = z.strictObject({
  event_id: uuidSchema,
  event_source: z.enum([
    'homework',
    'journal',
    'schedule',
    'gateway',
    'backoffice',
    'billing',
    'documents',
  ]),
  event_type: z.string(),
  schema_version: z.literal(1),
  occurred_at: z.iso.datetime({ offset: true }),
  request_id: z.string().nullable(),
  actor: z.strictObject({
    source: z.enum(['gateway', 'backoffice', 'system', 'service']),
    id: z.string(),
  }),
  payload: z.record(z.string(), z.unknown()),
});
const schoolClass = z.strictObject({
  id: positiveIdSchema,
  name: z.string(),
  study_year: z.number().int(),
  created_at: z.iso.datetime({ offset: true }),
});

export function createAnalyticsApi(client: ApiClient) {
  return {
    getProgress(classId: number, from: string, to: string, signal?: AbortSignal) {
      const query = new URLSearchParams({
        class_id: String(positiveIdSchema.parse(classId)),
        date_from: daySchema.parse(from),
        date_to: daySchema.parse(to),
      });
      return client.json(
        `/api/v1/analytics/progress?${query}`,
        { signal },
        z.array(progressRow).max(1000),
      );
    },
    getAudit(from: string, to: string, offset: number, signal?: AbortSignal) {
      const query = new URLSearchParams({
        date_from: daySchema.parse(from),
        date_to: daySchema.parse(to),
        limit: '50',
        offset: String(offset),
      });
      return client.json(
        `/api/v1/analytics/audit?${query}`,
        { signal },
        z.array(auditEvent).max(50),
      );
    },
    getClasses(offset: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/analytics/classes?offset=${offset}`,
        { signal },
        z.array(schoolClass).max(100),
      );
    },
  };
}
