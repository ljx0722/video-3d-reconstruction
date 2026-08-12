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

export function getPointMaterialProfile(mode: ViewerMode, pointSize: number, opacity: number) {
  const soft = mode === 'gaussian';
  return {
    size: soft ? pointSize * 1.75 : pointSize,
    opacity: soft ? Math.min(opacity, 0.8) : opacity,
    blending: THREE.NormalBlending,
    depthTest: true,
    depthWrite: true,
    alphaTest: soft ? 0.05 : 0,
    useSoftTexture: soft,
  };
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

export function createPresentationMaterial(hasVertexColors: boolean, map: THREE.Texture | null = null) {
  if (map) map.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshStandardMaterial({
    color: hasVertexColors || map ? 0xffffff : 0xc7cbd1,
    map,
    vertexColors: hasVertexColors,
    metalness: 0,
    roughness: 0.82,
    emissive: 0x000000,
    side: THREE.DoubleSide,
    flatShading: false,
    depthTest: true,
    depthWrite: true,
    transparent: false,
    toneMapped: true,
  });
}
