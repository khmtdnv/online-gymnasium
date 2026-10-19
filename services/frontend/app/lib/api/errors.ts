import { apiErrorEnvelopeSchema } from './contracts';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class ApiProtocolError extends Error {
  constructor(public readonly requestId?: string) {
    super('Сервис вернул ответ, который не соответствует ожидаемому формату.');
    this.name = 'ApiProtocolError';
  }
}

export class ApiNetworkError extends Error {
  constructor() {
    super('Не удалось связаться с сервером. Проверьте соединение.');
    this.name = 'ApiNetworkError';
  }
}

/** Ответ прошлого аккаунта не должен попасть в кеш новой сессии. */
export class SessionChangedError extends Error {
  constructor() {
    super('Сессия изменилась. Повторите чтение данных.');
    this.name = 'SessionChangedError';
  }
}

export async function responseError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const parsed = apiErrorEnvelopeSchema.safeParse(body);
  return new ApiError(
    response.status,
    parsed.success ? parsed.data.error.code : 'http_error',
    parsed.success ? parsed.data.error.message : 'Request failed',
    parsed.success
      ? parsed.data.error.request_id
      : (response.headers.get('X-Request-ID') ?? undefined),
  );
}

/** Клиентский текст не показывает traceback и не зависит от языка HTTP detail. */
export function explainError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Сессия истекла. Войдите снова.';
    if (error.status === 403) return 'Для этого действия недостаточно прав.';
    if (error.status === 404) return 'Запрошенные данные не найдены.';
    if (error.status === 409) {
      if (/version/i.test(error.code) || /version/i.test(error.message))
        return 'Урок уже изменён. Сверьте обновлённое расписание; введённые данные сохранены.';
      if (/idempotency/i.test(error.code) || /Idempotency/i.test(error.message))
        return 'Эта попытка создания уже использовала другие данные. Начните новую попытку.';
      return 'Действие конфликтует с текущим состоянием. Проверьте расписание и повторите вручную.';
    }
    if (error.status === 422) return 'Проверьте введённые значения и повторите отправку.';
    return 'Сервис временно недоступен. Попробуйте позже.';
  }
  if (
    error instanceof ApiProtocolError ||
    error instanceof ApiNetworkError ||
    error instanceof SessionChangedError
  )
    return error.message;
  return 'Не удалось выполнить действие. Попробуйте ещё раз.';
}

export function errorRequestId(error: unknown): string | undefined {
  return error instanceof ApiError || error instanceof ApiProtocolError
    ? error.requestId
    : undefined;
}
