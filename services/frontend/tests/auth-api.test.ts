import { expect, it, vi } from 'vitest';
import { createAuthApi } from '../app/features/auth/auth-api';
import { ApiProtocolError } from '../app/lib/api/errors';

it('не позволяет redirect перенести пароль или cookie на другой endpoint', async () => {
  const fetchImpl = vi
    .fn<typeof fetch>()
    .mockResolvedValue(Response.json({ access_token: 'test' }));
  await createAuthApi(fetchImpl).login('qa@example.test', 'test-only');
  expect(fetchImpl).toHaveBeenCalledWith(
    '/api/v1/auth/login',
    expect.objectContaining({ redirect: 'error', cache: 'no-store', credentials: 'same-origin' }),
  );
});
it('выход требует именно согласованный 204, а не произвольный успешный HTML', async () => {
  const fetchImpl = vi
    .fn<typeof fetch>()
    .mockResolvedValue(new Response('<html>', { status: 200 }));
  await expect(createAuthApi(fetchImpl).logout()).rejects.toBeInstanceOf(ApiProtocolError);
});
it('принимает logout 204', async () => {
  const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
  await expect(createAuthApi(fetchImpl).logout()).resolves.toBeUndefined();
});
