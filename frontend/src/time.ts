const BEIJING_TIME_ZONE = 'Asia/Shanghai';

function parseDate(value: Date | string | number): Date {
  if (value instanceof Date || typeof value === 'number') return new Date(value);
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

export function formatBeijingDateTime(value: Date | string | number): string {
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return typeof value === 'string' ? value : '';

  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${values.year}年${values.month}月${values.day}日 ${values.hour}时${values.minute}分${values.second}秒`;
}
