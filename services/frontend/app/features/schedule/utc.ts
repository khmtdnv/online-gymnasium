/** Отображение времени расписания административных экранов в UTC. */

export function utcTime(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'UTC',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function utcDateTime(value: string): string {
  const withZone = /(Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return `${new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(withZone))} UTC`;
}
