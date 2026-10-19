import { index, layout, route, type RouteConfig } from '@react-router/dev/routes';

export default [
  route('login', 'routes/login.tsx'),
  layout('routes/protected.tsx', [
    index('routes/home.tsx'),
    route('profile', 'routes/profile.tsx'),
    layout('routes/operational.tsx', [
      route('schedule', 'routes/schedule.tsx'),
      route('workload', 'routes/workload.tsx'),
      route('documents', 'routes/documents.tsx'),
      route('documents/:jobId', 'routes/document-job.tsx'),
    ]),
    route('*', 'routes/not-found.tsx'),
  ]),
] satisfies RouteConfig;
