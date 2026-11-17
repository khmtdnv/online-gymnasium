import type { ApiClient } from '../../lib/api/client';
import { daySchema, positiveIdSchema, workloadSchema } from '../../lib/api/contracts';

export function createWorkloadApi(client: ApiClient) {
  return {
    getWorkload(classId: number, day: string, signal?: AbortSignal) {
      const query = new URLSearchParams({
        class_id: String(positiveIdSchema.parse(classId)),
        day: daySchema.parse(day),
      });
      return client.json(`/api/v1/analytics/workload?${query}`, { signal }, workloadSchema);
    },
  };
}
