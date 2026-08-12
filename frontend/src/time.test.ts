import { describe, expect, it } from 'vitest';
import { formatBeijingDateTime } from './time';

describe('Beijing time formatting', () => {
  it('formats current timestamps with Chinese date and time units', () => {
    expect(formatBeijingDateTime(new Date('2026-08-12T12:34:56Z')))
      .toBe('2026年08月12日 20时34分56秒');
  });

  it('interprets backend timezone-less timestamps as UTC', () => {
    expect(formatBeijingDateTime('2026-08-12T12:34:56'))
      .toBe('2026年08月12日 20时34分56秒');
  });

  it('preserves explicitly offset timestamps', () => {
    expect(formatBeijingDateTime('2026-08-12T20:34:56+08:00'))
      .toBe('2026年08月12日 20时34分56秒');
  });
});
