import { describe, expect, it, vi } from 'vitest';
import { enterBackoffice } from '../app/features/auth/backoffice-sso';

describe('переход в Backoffice', () => {
  it('передаёт токен и CSRF в POST и открывает нужный раздел', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const navigate = vi.fn();
    await enterBackoffice(
      '/admin/analytics/',
      'access-token',
      fetchImpl,
      () => 'csrf-token',
      navigate,
    );
    expect(fetchImpl).toHaveBeenCalledWith(
      '/admin/sso/',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer access-token', 'X-CSRFToken': 'csrf-token' },
      }),
    );
    expect(navigate).toHaveBeenCalledWith('/admin/analytics/');
  });

  it('не открывает раздел при отказе в доступе', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));
    const navigate = vi.fn();
    await expect(
      enterBackoffice('/admin/', 'token', fetchImpl, () => 'csrf', navigate),
    ).rejects.toThrow();
    expect(navigate).not.toHaveBeenCalled();
  });
});
