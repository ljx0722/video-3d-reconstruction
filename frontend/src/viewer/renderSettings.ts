import { useCallback, useEffect, useState } from 'react';

export type PointShape = 'square' | 'circle';
export type GaussianBlend = 'normal' | 'additive';
export type RenderPresetName = 'natural' | 'bright' | 'dark' | 'detail' | 'performance';

export interface ViewerRenderSettings {
  backgroundColor: string;
  exposure: number;
  bloomStrength: number;
  bloomThreshold: number;
  bloomSmoothing: number;
  lightIntensity: number;
  ambientLight: number;
  keyLight: number;
  fillLight: number;
  rimLight: number;
  fov: number;
  orthographic: boolean;
  showAxes: boolean;
  showGrid: boolean;
  showTrajectory: boolean;
  pointSize: number;
  pointOpacity: number;
  pointShape: PointShape;
  pointDepthTest: boolean;
  colorMode: string;
  gaussianRadius: number;
  gaussianOpacity: number;
  gaussianFalloff: number;
  gaussianEdgeCutoff: number;
  gaussianBlend: GaussianBlend;
  gaussianDepthWrite: boolean;
  surfaceRoughness: number;
  surfaceMetalness: number;
  surfaceColorBrightness: number;
  surfaceFlatShading: boolean;
  surfaceDoubleSide: boolean;
  edgeThreshold: number;
  edgeColor: string;
  edgeOpacity: number;
}

export const RENDER_SETTINGS_VERSION = 1;
export const RENDER_SETTINGS_STORAGE_KEY = 'video3d.viewer.render-settings.v1';

export const DEFAULT_VIEWER_RENDER_SETTINGS: ViewerRenderSettings = {
  backgroundColor: '#101923',
  exposure: 1,
  bloomStrength: 0,
  bloomThreshold: 0.9,
  bloomSmoothing: 0.05,
  lightIntensity: 1,
  ambientLight: 0.35,
  keyLight: 2.2,
  fillLight: 1.1,
  rimLight: 1.5,
  fov: 50,
  orthographic: false,
  showAxes: false,
  showGrid: false,
  showTrajectory: true,
  pointSize: 0.004,
  pointOpacity: 1,
  pointShape: 'square',
  pointDepthTest: true,
  colorMode: 'rgb',
  gaussianRadius: 4,
  gaussianOpacity: 0.75,
  gaussianFalloff: 2,
  gaussianEdgeCutoff: 0,
  gaussianBlend: 'normal',
  gaussianDepthWrite: false,
  surfaceRoughness: 0.82,
  surfaceMetalness: 0,
  surfaceColorBrightness: 1,
  surfaceFlatShading: false,
  surfaceDoubleSide: true,
  edgeThreshold: 30,
  edgeColor: '#6f89a3',
  edgeOpacity: 0.72,
};

const PRESETS: Record<RenderPresetName, Partial<ViewerRenderSettings>> = {
  natural: {},
  bright: {
    exposure: 1.25,
    lightIntensity: 1.2,
    surfaceColorBrightness: 1.15,
    bloomStrength: 0.1,
  },
  dark: {
    backgroundColor: '#070b11',
    exposure: 0.8,
    lightIntensity: 0.75,
    bloomStrength: 0,
  },
  detail: {
    exposure: 1.05,
    pointSize: 0.0025,
    pointOpacity: 0.95,
    gaussianRadius: 3,
    gaussianFalloff: 2.8,
    surfaceRoughness: 0.62,
    edgeThreshold: 18,
    edgeOpacity: 0.9,
  },
  performance: {
    bloomStrength: 0,
    pointSize: 0.003,
    gaussianRadius: 2.5,
    surfaceRoughness: 0.9,
    edgeThreshold: 45,
  },
};

const NUMBER_RANGES: Record<string, readonly [number, number]> = {
  exposure: [0.4, 2],
  bloomStrength: [0, 0.5],
  bloomThreshold: [0.5, 1],
  bloomSmoothing: [0, 0.5],
  lightIntensity: [0.25, 2],
  ambientLight: [0, 3],
  keyLight: [0, 3],
  fillLight: [0, 3],
  rimLight: [0, 3],
  fov: [30, 90],
  pointSize: [0.001, 0.05],
  pointOpacity: [0.1, 1],
  gaussianRadius: [1, 8],
  gaussianOpacity: [0.1, 0.9],
  gaussianFalloff: [0.5, 4],
  gaussianEdgeCutoff: [0, 0.1],
  surfaceRoughness: [0.2, 1],
  surfaceMetalness: [0, 0.4],
  surfaceColorBrightness: [0.5, 1.5],
  edgeThreshold: [1, 80],
  edgeOpacity: [0.1, 1],
};

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function validHex(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
}

export function normalizeViewerRenderSettings(value: unknown): ViewerRenderSettings {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const normalized = { ...DEFAULT_VIEWER_RENDER_SETTINGS } as ViewerRenderSettings;

  for (const [key, [minimum, maximum]] of Object.entries(NUMBER_RANGES)) {
    const settingKey = key as keyof ViewerRenderSettings;
    normalized[settingKey] = clamp(
      finiteNumber(source[key], DEFAULT_VIEWER_RENDER_SETTINGS[settingKey] as number),
      minimum,
      maximum,
    ) as never;
  }

  normalized.backgroundColor = validHex(source.backgroundColor, normalized.backgroundColor);
  normalized.edgeColor = validHex(source.edgeColor, normalized.edgeColor);
  normalized.orthographic = typeof source.orthographic === 'boolean' ? source.orthographic : normalized.orthographic;
  normalized.showAxes = typeof source.showAxes === 'boolean' ? source.showAxes : normalized.showAxes;
  normalized.showGrid = typeof source.showGrid === 'boolean' ? source.showGrid : normalized.showGrid;
  normalized.showTrajectory = typeof source.showTrajectory === 'boolean' ? source.showTrajectory : normalized.showTrajectory;
  normalized.pointDepthTest = typeof source.pointDepthTest === 'boolean' ? source.pointDepthTest : normalized.pointDepthTest;
  normalized.surfaceFlatShading = typeof source.surfaceFlatShading === 'boolean' ? source.surfaceFlatShading : normalized.surfaceFlatShading;
  normalized.surfaceDoubleSide = typeof source.surfaceDoubleSide === 'boolean' ? source.surfaceDoubleSide : normalized.surfaceDoubleSide;
  normalized.gaussianDepthWrite = typeof source.gaussianDepthWrite === 'boolean' ? source.gaussianDepthWrite : normalized.gaussianDepthWrite;
  normalized.pointShape = source.pointShape === 'circle' ? 'circle' : normalized.pointShape;
  normalized.gaussianBlend = source.gaussianBlend === 'additive' ? 'additive' : normalized.gaussianBlend;
  normalized.colorMode = typeof source.colorMode === 'string' ? source.colorMode : normalized.colorMode;
  return normalized;
}

export function getRenderPreset(name: RenderPresetName): ViewerRenderSettings {
  return normalizeViewerRenderSettings({ ...DEFAULT_VIEWER_RENDER_SETTINGS, ...PRESETS[name] });
}

export function readViewerRenderSettings(storage: Storage | null | undefined): ViewerRenderSettings {
  if (!storage) return { ...DEFAULT_VIEWER_RENDER_SETTINGS };
  try {
    const raw = storage.getItem(RENDER_SETTINGS_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_VIEWER_RENDER_SETTINGS };
    const parsed = JSON.parse(raw) as { version?: unknown; settings?: unknown };
    if (parsed?.version !== RENDER_SETTINGS_VERSION) return { ...DEFAULT_VIEWER_RENDER_SETTINGS };
    return normalizeViewerRenderSettings(parsed.settings);
  } catch {
    return { ...DEFAULT_VIEWER_RENDER_SETTINGS };
  }
}

export function useViewerRenderSettings() {
  const [settings, setSettings] = useState<ViewerRenderSettings>(() => (
    typeof window === 'undefined' ? { ...DEFAULT_VIEWER_RENDER_SETTINGS } : readViewerRenderSettings(window.localStorage)
  ));

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(RENDER_SETTINGS_STORAGE_KEY, JSON.stringify({
          version: RENDER_SETTINGS_VERSION,
          settings,
        }));
      } catch {
        // Storage may be unavailable or quota-limited; rendering remains local.
      }
    }, 120);
    return () => window.clearTimeout(timer);
  }, [settings]);

  const updateSetting = useCallback(<K extends keyof ViewerRenderSettings>(key: K, value: ViewerRenderSettings[K]) => {
    setSettings(previous => normalizeViewerRenderSettings({ ...previous, [key]: value }));
  }, []);

  const applyPreset = useCallback((name: RenderPresetName) => {
    setSettings(getRenderPreset(name));
  }, []);

  const reset = useCallback(() => {
    setSettings({ ...DEFAULT_VIEWER_RENDER_SETTINGS });
  }, []);

  return { settings, updateSetting, applyPreset, reset };
}
