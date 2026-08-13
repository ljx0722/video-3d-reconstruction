import { describe, expect, it } from 'vitest';
import {
  DEFAULT_VIEWER_RENDER_SETTINGS,
  RENDER_SETTINGS_STORAGE_KEY,
  RENDER_SETTINGS_VERSION,
  getRenderPreset,
  normalizeViewerRenderSettings,
  readViewerRenderSettings,
} from './renderSettings';

function storage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: key => { values.delete(key); },
    clear: () => { values.clear(); },
    key: index => Array.from(values.keys())[index] ?? null,
    get length() { return values.size; },
  } as Storage;
}

describe('viewer render settings', () => {
  it('clamps numeric values and rejects invalid enum/color values', () => {
    const settings = normalizeViewerRenderSettings({
      exposure: 100,
      pointSize: -1,
      surfaceMetalness: Number.NaN,
      backgroundColor: 'red',
      pointShape: 'triangle',
      gaussianBlend: 'multiply',
    });

    expect(settings.exposure).toBe(2);
    expect(settings.pointSize).toBe(0.001);
    expect(settings.surfaceMetalness).toBe(DEFAULT_VIEWER_RENDER_SETTINGS.surfaceMetalness);
    expect(settings.backgroundColor).toBe(DEFAULT_VIEWER_RENDER_SETTINGS.backgroundColor);
    expect(settings.pointShape).toBe('square');
    expect(settings.gaussianBlend).toBe('normal');
  });

  it('reads only the current version from storage', () => {
    const current = storage({
      [RENDER_SETTINGS_STORAGE_KEY]: JSON.stringify({
        version: RENDER_SETTINGS_VERSION,
        settings: { exposure: 1.5 },
      }),
    });
    expect(readViewerRenderSettings(current).exposure).toBe(1.5);

    const old = storage({
      [RENDER_SETTINGS_STORAGE_KEY]: JSON.stringify({ version: 0, settings: { exposure: 1.5 } }),
    });
    expect(readViewerRenderSettings(old).exposure).toBe(DEFAULT_VIEWER_RENDER_SETTINGS.exposure);
  });

  it('keeps presets within the public ranges', () => {
    for (const name of ['natural', 'bright', 'dark', 'detail', 'performance'] as const) {
      const preset = getRenderPreset(name);
      expect(preset.exposure).toBeGreaterThanOrEqual(0.4);
      expect(preset.exposure).toBeLessThanOrEqual(2);
      expect(preset.edgeThreshold).toBeGreaterThanOrEqual(1);
      expect(preset.edgeThreshold).toBeLessThanOrEqual(80);
    }
  });
});
