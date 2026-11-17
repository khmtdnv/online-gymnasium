/** Передаёт access-токен только серверу Backoffice и открывает его раздел. */
export async function enterBackoffice(
  target: string,
  accessToken: string,
  fetchImpl: typeof fetch,
  readCsrf: () => string | null,
  navigate: (target: string) => void,
): Promise<void> {
  if (!target.startsWith('/admin/')) throw new Error('Недопустимый адрес админки.');
  const csrfResponse = await fetchImpl('/admin/sso/csrf/', { credentials: 'same-origin' });
  const csrf = readCsrf();
  if (!csrfResponse.ok || !csrf) throw new Error('Не удалось подготовить вход в админку.');
  const response = await fetchImpl('/admin/sso/', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Authorization: `Bearer ${accessToken}`, 'X-CSRFToken': csrf },
  });
  if (!response.ok) throw new Error('Нет доступа к админке или вход временно недоступен.');
  navigate(target);
}

/** Читает CSRF-cookie Django, не затрагивая HttpOnly refresh-cookie. */
export function readCsrfCookie(): string | null {
  const cookie = document.cookie.split('; ').find((item) => item.startsWith('csrftoken='));
  return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : null;
}
