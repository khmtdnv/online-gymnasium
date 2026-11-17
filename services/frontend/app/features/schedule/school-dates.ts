/** Даты школы не зависят от timezone устройства. */
export const schoolTimezone = 'Asia/Yekaterinburg';
export function schoolDay(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: schoolTimezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const part = (name: string) => parts.find((p) => p.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function addSchoolDays(day: string, amount: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}
export function schoolWeek(day = schoolDay()): string {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return addSchoolDays(day, weekday === 0 ? 1 : 1 - weekday);
}
export function formatSchoolDay(day: string, options: Intl.DateTimeFormatOptions = {}): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString('ru-RU', {
    timeZone: schoolTimezone,
    day: 'numeric',
    month: 'long',
    ...options,
  });
}
export function schoolTime(instant: string): string {
  return new Date(instant).toLocaleTimeString('ru-RU', {
    timeZone: schoolTimezone,
    hour: '2-digit',
    minute: '2-digit',
  });
}
export function schoolDatetime(instant: string): string {
  return `${formatSchoolDay(schoolDay(new Date(instant)))} в ${schoolTime(instant)}`;
}
