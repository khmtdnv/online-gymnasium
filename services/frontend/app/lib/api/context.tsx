import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useSession } from '../../features/auth/session-context';
import { createScheduleApi } from '../../features/schedule/api';
import { createWorkloadApi } from '../../features/workload/api';
import { createDocumentsApi } from '../../features/documents/api';
import { createHomeworkApi } from '../../features/homework/api';
import { createApiClient } from './client';
import { createAnalyticsApi } from '../../features/analytics/api';
import { createPenApi } from '../../features/pen/contracts';
import { createBillingApi } from '../../features/billing/api';
import { createNotificationsApi } from '../../features/notifications/api';

export interface Features {
  notifications: ReturnType<typeof createNotificationsApi>;
  billing: ReturnType<typeof createBillingApi>;
  pen: ReturnType<typeof createPenApi>;
  analytics: ReturnType<typeof createAnalyticsApi>;
  schedule: ReturnType<typeof createScheduleApi>;
  workload: ReturnType<typeof createWorkloadApi>;
  documents: ReturnType<typeof createDocumentsApi>;
  homework: ReturnType<typeof createHomeworkApi>;
}
export const FeaturesContext = createContext<Features | null>(null);

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const features = useMemo(() => {
    if (!session) return null;
    const client = createApiClient({ fetchImpl: window.fetch.bind(window), session });
    return {
      notifications: createNotificationsApi(client),
      billing: createBillingApi(client),
      pen: createPenApi(client),
      analytics: createAnalyticsApi(client),
      schedule: createScheduleApi(client),
      workload: createWorkloadApi(client),
      documents: createDocumentsApi(client),
      homework: createHomeworkApi(client),
    };
  }, [session]);
  return <FeaturesContext.Provider value={features}>{children}</FeaturesContext.Provider>;
}

export function useFeatures(): Features {
  const features = useContext(FeaturesContext);
  if (!features) throw new Error('API недоступен до проверки сессии.');
  return features;
}
