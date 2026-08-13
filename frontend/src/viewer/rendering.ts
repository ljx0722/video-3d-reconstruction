import * as THREE from 'three';

export type ViewerMode = 'points' | 'gaussian' | 'mesh' | 'wireframe';

export function srgbToLinear(value: number) {
  const srgb = Math.max(0, Math.min(1, value));
  return srgb <= 0.04045 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
}

export function linearToSrgb(value: number) {
  const linear = Math.max(0, Math.min(1, value));
  return linear <= 0.0031308 ? linear * 12.92 : 1.055 * Math.pow(linear, 1 / 2.4) - 0.055;
}

export function decodeArtifactColor(value: number, colorsAreLinear: boolean) {
  return colorsAreLinear ? Math.max(0, Math.min(1, value)) : srgbToLinear(value);
}

export interface PointMaterialOptions {
  gaussianRadius?: number;
  gaussianOpacity?: number;
  gaussianFalloff?: number;
  gaussianEdgeCutoff?: number;
  gaussianBlend?: 'normal' | 'additive';
  gaussianDepthWrite?: boolean;
  pointShape?: 'square' | 'circle';
  pointDepthTest?: boolean;
}

export function getPointMaterialProfile(
  mode: ViewerMode,
  pointSize: number,
  opacity: number,
  options: PointMaterialOptions = {},
) {
  const soft = mode === 'gaussian';
  const gaussianRadius = options.gaussianRadius ?? 4;
  const gaussianOpacity = options.gaussianOpacity ?? 0.75;
  const blending = soft && options.gaussianBlend === 'additive'
    ? THREE.AdditiveBlending
    : THREE.NormalBlending;
  return {
    size: soft ? pointSize * gaussianRadius : pointSize,
    opacity: soft ? Math.min(opacity, gaussianOpacity, blending === THREE.AdditiveBlending ? 0.35 : 0.9) : opacity,
    blending,
    depthTest: options.pointDepthTest ?? true,
    depthWrite: soft ? (options.gaussianDepthWrite ?? false) : true,
    alphaTest: soft ? (options.gaussianEdgeCutoff ?? 0) : 0,
    useSoftTexture: soft,
    gaussianFalloff: options.gaussianFalloff ?? 2,
    pointShape: options.pointShape ?? 'square',
  };
}

export function createCircleTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 32;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.fillStyle = '#fff';
  context.beginPath();
  context.arc(16, 16, 15.5, 0, Math.PI * 2);
  context.fill();
  const texture = new THREE.CanvasTexture(canvas);
  texture.name = 'ModelLoader circular point texture';
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = false;
  return texture;
}

export function createGaussianTexture(falloff = 2, edgeCutoff = 0) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 32;
  const context = canvas.getContext('2d');
  if (!context) return null;
  const gradient = context.createRadialGradient(16, 16, 0, 16, 16, 16);
  const edge = Math.max(0, Math.min(0.1, edgeCutoff));
  const power = Math.max(0.5, Math.min(4, falloff));
  const stops = 16;
  for (let index = 0; index <= stops; index += 1) {
    const radius = index / stops;
    const alpha = radius >= 1 - edge ? 0 : Math.pow(Math.max(0, 1 - radius), power);
    gradient.addColorStop(radius, `rgba(255,255,255,${alpha})`);
  }
  context.fillStyle = gradient;
  context.fillRect(0, 0, 32, 32);
  const texture = new THREE.CanvasTexture(canvas);
  texture.name = 'ModelLoader gaussian radial texture';
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = false;
  return texture;
}

export function createPointColors(mode: string, positions: Float32Array, rgb: Float32Array) {
  if (mode === 'rgb') return rgb.slice();

  const colors = new Float32Array(positions.length);
  const axis = mode === 'height' ? 1 : mode === 'depth' ? 2 : -1;
  if (axis < 0) {
    colors.fill(0.8);
    return colors;
  }

  let minimum = Infinity;
  let maximum = -Infinity;
  for (let index = axis; index < positions.length; index += 3) {
    minimum = Math.min(minimum, positions[index]);
    maximum = Math.max(maximum, positions[index]);
  }
  const range = maximum - minimum || 1;
  for (let index = 0; index < positions.length; index += 3) {
    const value = Math.max(0, Math.min(1, (positions[index + axis] - minimum) / range));
    if (axis === 1) {
      colors[index] = value * 0.9 + 0.05;
      colors[index + 1] = (1 - value) * 0.7 + 0.1;
      colors[index + 2] = (1 - value) * 0.85 + 0.1;
    } else {
      colors[index] = 1 - value * 0.7;
      colors[index + 1] = value * 0.9;
      colors[index + 2] = 0.2;
    }
  }
  return colors;
}

export interface PresentationMaterialOptions {
  roughness?: number;
  metalness?: number;
  colorBrightness?: number;
  flatShading?: boolean;
  doubleSide?: boolean;
}

export function createPresentationMaterial(
  hasVertexColors: boolean,
  map: THREE.Texture | null = null,
  options: PresentationMaterialOptions = {},
) {
  if (map) map.colorSpace = THREE.SRGBColorSpace;
  const brightness = Math.max(0.5, Math.min(1.5, options.colorBrightness ?? 1));
  return new THREE.MeshStandardMaterial({
    color: hasVertexColors || map ? new THREE.Color(brightness, brightness, brightness) : new THREE.Color(0xc7cbd1).multiplyScalar(brightness),
    map,
    vertexColors: hasVertexColors,
    metalness: Math.max(0, Math.min(0.4, options.metalness ?? 0)),
    roughness: Math.max(0.2, Math.min(1, options.roughness ?? 0.82)),
    emissive: 0x000000,
    side: options.doubleSide === false ? THREE.FrontSide : THREE.DoubleSide,
    flatShading: options.flatShading ?? false,
    depthTest: true,
    depthWrite: true,
    transparent: false,
    toneMapped: true,
  });
}
