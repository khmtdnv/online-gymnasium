export const scheduleKeys = {
  day: (classId: number, day: string) => ['schedule', classId, day] as const,
};
export const workloadKeys = {
  day: (classId: number, day: string) => ['workload', classId, day] as const,
};
