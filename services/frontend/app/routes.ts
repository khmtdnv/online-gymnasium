import { index, layout, route, type RouteConfig } from '@react-router/dev/routes';

export default [
  route('login', 'routes/login.tsx'),
  layout('routes/protected.tsx', [
    index('routes/home.tsx'),
    route('profile', 'routes/profile.tsx'),
    route('billing', 'routes/billing.tsx'),
    route('notifications', 'routes/notifications.tsx'),
    route('my-schedule', 'routes/schedule-redirect.tsx'),
    route('schedule', 'routes/schedule-by-role.tsx'),
    route('diary', 'routes/diary.tsx'),
    route('pen/lessons/:lessonId', 'routes/pen.tsx'),
    route('homework', 'routes/homework.tsx'),
    route('homework/:homeworkId', 'routes/homework-detail.tsx'),
    route('lessons/:lessonId', 'routes/teacher-lesson.tsx'),
    layout('routes/operational.tsx', [
      route('analytics', 'routes/analytics.tsx'),
      route('workload', 'routes/workload.tsx'),
      route('documents', 'routes/documents.tsx'),
      route('documents/:jobId', 'routes/document-job.tsx'),
    ]),
    route('*', 'routes/not-found.tsx'),
  ]),
] satisfies RouteConfig;
