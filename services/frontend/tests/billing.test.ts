import { expect, it } from 'vitest';
import { createBillingApi, paymentSchema } from '../app/features/billing/api';
import { createApiClient } from '../app/lib/api/client';
import { ApiError, explainError } from '../app/lib/api/errors';

it('объясняет, как восстановить доступ при неоплате', () => {
  expect(explainError(new ApiError(403, 'tuition_payment_required', 'Payment required'))).toMatch(
    /оплат/i,
  );
});

it('повторяет checkout с тем же ключом без суммы и не принимает чужой redirect', async () => {
  const bodies: unknown[] = [];
  const student = '00000000-0000-4000-8000-000000000003';
  const payer = '00000000-0000-4000-8000-000000000004';
  const key = '00000000-0000-4000-8000-000000000005';
  const payment = {
    id: 1,
    order_id: 2,
    student_id: student,
    payer_id: payer,
    study_month: '2026-10-01',
    amount_kopecks: 300000,
    currency: 'RUB',
    status: 'pending',
    confirmation_url: 'https://yoomoney.ru/test',
    provider_id: null,
    created_at: '2026-10-22T12:00:00Z',
    refund_status: null,
  };
  const client = createApiClient({
    session: {
      getAccessToken: () => 'token',
      getEpoch: () => 1,
      refresh: async () => 'new-token',
      invalidate: () => undefined,
    },
    fetchImpl: async (_url, init) => {
      bodies.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify(payment), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      });
    },
  });
  const api = createBillingApi(client);
  await api.start(student, '2026-10-01', key);
  await api.start(student, '2026-10-01', key);
  expect(bodies).toEqual([
    { student_id: student, study_month: '2026-10-01', request_key: key },
    { student_id: student, study_month: '2026-10-01', request_key: key },
  ]);
  expect(
    paymentSchema.safeParse({ ...payment, confirmation_url: 'https://yoomoney.ru.evil.test/pay' })
      .success,
  ).toBe(false);
  await api.start(student, '2026-09-01', key, 'quarter');
  expect(bodies.at(-1)).toEqual({
    student_id: student,
    study_month: '2026-09-01',
    request_key: key,
    period_type: 'quarter',
  });
});
