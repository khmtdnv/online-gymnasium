import type { DocumentJob } from '../../lib/api/contracts';

/** Пауза после двух минут — клиентская экономия запросов, не ошибка задания. */
export function getDocumentPollInterval(
  elapsedMs: number,
  status: DocumentJob['status'],
): number | false {
  if (status === 'completed' || status === 'failed' || elapsedMs >= 120_000) return false;
  return elapsedMs < 60_000 ? 2_000 : 5_000;
}
