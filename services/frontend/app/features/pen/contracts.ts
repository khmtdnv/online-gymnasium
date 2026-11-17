import { z } from 'zod';
import { positiveIdSchema, uuidSchema } from '../../lib/api/contracts';
import type { ApiClient } from '../../lib/api/client';

const point = z.strictObject({ x: z.number().min(0).max(1), y: z.number().min(0).max(1) });
export type PenPoint = z.infer<typeof point>;
export const penBatchSchema = z.strictObject({
  batch_id: uuidSchema,
  sequence: z.number().int().min(1).max(4096),
  stroke_id: uuidSchema,
  points: z.array(point).min(1).max(64),
  finished: z.boolean(),
});
export type PenBatch = z.infer<typeof penBatchSchema>;
const savedBatch = penBatchSchema.extend({ id: z.number().int().positive() });
export type SavedPenBatch = z.infer<typeof savedBatch>;
export const penMessageSchema = z.discriminatedUnion('type', [
  z.strictObject({ type: z.literal('batch'), batch: savedBatch }),
  z.strictObject({ type: z.literal('ack'), batch: savedBatch }),
  z.strictObject({ type: z.literal('ready'), after: z.number().int().min(0).max(4096) }),
]);

export function createPenApi(client: ApiClient) {
  return {
    listStudents(lessonId: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/pen/lessons/${positiveIdSchema.parse(lessonId)}/students`,
        { signal },
        z.array(z.strictObject({ id: uuidSchema, name: z.string().min(1) })).max(1000),
      );
    },
  };
}
