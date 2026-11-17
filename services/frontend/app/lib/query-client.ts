import { QueryClient } from '@tanstack/react-query';
import { ApiError, ApiProtocolError, SessionChangedError } from './api/errors';

/** Записи не повторяются автоматически; чтения получают одну попытку при сбое. */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retry: (attempt, error) =>
          attempt < 1 &&
          !(error instanceof ApiProtocolError || error instanceof SessionChangedError) &&
          (!(error instanceof ApiError) || error.status >= 500),
      },
      mutations: { retry: false },
    },
  });
}
