import { apiErrorEnvelopeSchema } from './contracts';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
    public readonly retryAfterMs?: number,
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
  const retryAfter = response.headers.get('Retry-After');
  const retryAfterMs =
    retryAfter === null
      ? undefined
      : /^\d+$/.test(retryAfter)
        ? Number(retryAfter) * 1000
        : Math.max(0, Date.parse(retryAfter) - Date.now());
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
    Number.isFinite(retryAfterMs) ? retryAfterMs : undefined,
  );
}

/** Клиентский текст не показывает traceback и не зависит от языка HTTP detail. */
export function explainError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Сессия истекла. Войдите снова.';
    if (error.status === 403) {
      if (error.code === 'tuition_payment_required')
        return 'Доступ к занятиям ограничен. Оплатите текущую четверть в разделе «Оплата».';
      return 'Для этого действия недостаточно прав.';
    }
    if (error.status === 404) return 'Запрошенные данные не найдены.';
    if (error.status === 409) {
      if (error.code === 'homework_answer_conflict')
        return 'Состояние работы уже изменилось. Обновите ответы: работа могла быть сдана или проверена другим запросом.';
      if (error.code === 'homework_file_not_ready')
        return 'Файл ещё не загружен. Обновите работу после завершения загрузки.';
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
