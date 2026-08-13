import { describe, expect, it } from 'vitest';
import { mapDisplayedToSource, sourceToDisplayed } from './Sam2PromptPanel';

describe('Sam2PromptPanel coordinate mapping', () => {
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const source = { width: 800, height: 600 };

  it('maps a centered click to the source center under object-contain', () => {
    const mapped = mapDisplayedToSource(200, 150, rect, source.width, source.height);
    expect(mapped).toEqual({ x: 400, y: 300 });
  });

  it('round-trips source center back to display center', () => {
    const display = sourceToDisplayed(400, 300, rect, source.width, source.height);
    expect(display.x).toBeCloseTo(200);
    expect(display.y).toBeCloseTo(150);
  });

  it('returns null for clicks outside the letterboxed content', () => {
    const wide = { left: 0, top: 0, width: 800, height: 300 };
    expect(mapDisplayedToSource(10, 10, wide, 800, 600)).toBeNull();
  });

  it('returns null for degenerate containers', () => {
    expect(mapDisplayedToSource(10, 10, { left: 0, top: 0, width: 0, height: 0 }, 800, 600)).toBeNull();
  });
});
