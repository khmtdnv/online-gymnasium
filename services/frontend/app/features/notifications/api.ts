import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { instantSchema, positiveIdSchema, uuidSchema } from '../../lib/api/contracts';

const notification = z.strictObject({
  id: positiveIdSchema.max(2147483647),
  event_id: uuidSchema,
  recipient_id: uuidSchema,
  title: z.string().min(1).max(200),
  body: z.string().min(1).max(500),
  link: z.string().regex(/^\/(billing|homework\/[1-9][0-9]{0,9}|documents\/[0-9a-fA-F-]{36})$/),
  created_at: instantSchema,
  read_at: instantSchema.nullable(),
});

export function createNotificationsApi(client: ApiClient) {
  return {
    list: (offset: number, signal?: AbortSignal) =>
      client.json(
        `/api/v1/notifications?offset=${offset}`,
        { signal },
        z.array(notification).max(50),
      ),
    count: (signal?: AbortSignal) =>
      client.json(
        '/api/v1/notifications/count',
        { signal },
        z.strictObject({ unread: z.number().int().min(0).max(2147483647) }),
      ),
    markRead: (id: number) =>
      client.json(
        `/api/v1/notifications/${positiveIdSchema.parse(id)}/read`,
        { method: 'POST', body: '{}' },
        z.strictObject({ read: z.literal(true) }),
      ),
  };
}
