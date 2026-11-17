import { daySchema, instantSchema } from '../../lib/api/contracts';

/** datetime-local не содержит зоны: для расписания явно назначаем UTC. */
export function utcInputToIso(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (
    !match ||
    !daySchema.safeParse(match[1]).success ||
    match[1].startsWith('0000') ||
    Number(match[2]) > 23 ||
    Number(match[3]) > 59
  )
    throw new Error('Введите корректную дату и время UTC.');
  return new Date(`${value}:00Z`).toISOString();
}

export function isoToUtcInput(value: string): string {
  return new Date(instantSchema.parse(value)).toISOString().slice(0, 16);
}

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
