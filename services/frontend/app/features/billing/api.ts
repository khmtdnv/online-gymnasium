import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { daySchema, instantSchema, positiveIdSchema, uuidSchema } from '../../lib/api/contracts';

const price = z.number().int().min(100).max(100000000);
const redirect = z.string().refine((value) => {
  try {
    const url = new URL(value);
    return (
      url.protocol === 'https:' &&
      !url.username &&
      !url.password &&
      (!url.port || url.port === '443') &&
      ['yoomoney.ru', 'yookassa.ru'].some(
        (host) => url.hostname === host || url.hostname.endsWith('.' + host),
      )
    );
  } catch {
    return false;
  }
});
export const paymentSchema = z.strictObject({
  id: positiveIdSchema,
  order_id: positiveIdSchema,
  student_id: uuidSchema,
  payer_id: uuidSchema,
  study_month: daySchema,
  period_type: z.enum(['month', 'quarter']).default('month'),
  amount_kopecks: price,
  currency: z.literal('RUB'),
  status: z.enum([
    'creating',
    'pending',
    'succeeded',
    'canceled',
    'unknown',
    'manual_review',
    'refunded',
  ]),
  confirmation_url: redirect.nullable(),
  provider_id: uuidSchema.nullable(),
  created_at: instantSchema,
  refund_status: z
    .enum(['creating', 'pending', 'succeeded', 'canceled', 'unknown', 'manual_review'])
    .nullable(),
});
export type Payment = z.infer<typeof paymentSchema>;
const namedPaymentSchema = paymentSchema.extend({ student_name: z.string().min(1) });
const orderSchema = z.strictObject({
  id: positiveIdSchema,
  student_id: uuidSchema,
  study_month: daySchema,
  period_type: z.enum(['month', 'quarter']).default('month'),
  amount_kopecks: price,
  currency: z.literal('RUB'),
  status: z.enum(['unpaid', 'paid', 'refunded']),
  payment: paymentSchema.nullable(),
});

export function createBillingApi(client: ApiClient) {
  const post = (path: string, body?: unknown) =>
    client.json(
      `/api/v1/billing/${path}`,
      { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) },
      paymentSchema,
    );
  return {
    config: (signal?: AbortSignal) =>
      client.json(
        '/api/v1/billing/config',
        { signal },
        z.strictObject({
          configured: z.boolean(),
          test_only: z.literal(true),
          price_kopecks: price,
          quarter_price_kopecks: price.default(900000),
          currency: z.literal('RUB'),
        }),
      ),
    students: (signal?: AbortSignal) =>
      client.json(
        '/api/v1/billing/students',
        { signal },
        z.array(z.strictObject({ id: uuidSchema, name: z.string().min(1) })).max(100),
      ),
    orders: (student: string, offset: number, signal?: AbortSignal) =>
      client.json(
        `/api/v1/billing/orders?student_id=${uuidSchema.parse(student)}&offset=${offset}`,
        { signal },
        z.array(orderSchema).max(50),
      ),
    payments: (offset: number, signal?: AbortSignal) =>
      client.json(
        `/api/v1/billing/payments?offset=${offset}`,
        { signal },
        z.array(namedPaymentSchema).max(50),
      ),
    start: (student: string, month: string, key: string, period?: 'month' | 'quarter') =>
      post('payments', {
        student_id: uuidSchema.parse(student),
        study_month: daySchema.parse(month),
        request_key: uuidSchema.parse(key),
        ...(period ? { period_type: period } : {}),
      }),
    refresh: (id: number) => post(`payments/${positiveIdSchema.parse(id)}/refresh`),
    refund: (id: number, key: string) =>
      post(`payments/${positiveIdSchema.parse(id)}/refund`, { request_key: uuidSchema.parse(key) }),
    reconcile: (id: number, providerId?: string) =>
      post(`payments/${positiveIdSchema.parse(id)}/reconcile`, {
        provider_id: providerId ? uuidSchema.parse(providerId) : null,
      }),
  };
}
