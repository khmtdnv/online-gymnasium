import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useSession } from '../../features/auth/session-context';
import { createScheduleApi } from '../../features/schedule/api';
import { createWorkloadApi } from '../../features/workload/api';
import { createDocumentsApi } from '../../features/documents/api';
import { createApiClient } from './client';

export interface Features {
  schedule: ReturnType<typeof createScheduleApi>;
  workload: ReturnType<typeof createWorkloadApi>;
  documents: ReturnType<typeof createDocumentsApi>;
}
export const FeaturesContext = createContext<Features | null>(null);

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const features = useMemo(() => {
    if (!session) return null;
    const client = createApiClient({ fetchImpl: window.fetch.bind(window), session });
    return {
      schedule: createScheduleApi(client),
      workload: createWorkloadApi(client),
      documents: createDocumentsApi(client),
    };
  }, [session]);
  return <FeaturesContext.Provider value={features}>{children}</FeaturesContext.Provider>;
}

export function useFeatures(): Features {
  const features = useContext(FeaturesContext);
  if (!features) throw new Error('API недоступен до проверки сессии.');
  return features;
}
