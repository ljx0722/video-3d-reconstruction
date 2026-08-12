import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { createPointColors, createPresentationMaterial, decodeArtifactColor, getPointMaterialProfile, linearToSrgb, srgbToLinear } from './rendering';

describe('viewer rendering profiles', () => {
  it('restores the readable Gaussian splat profile without additive overexposure', () => {
    const profile = getPointMaterialProfile('gaussian', 0.004, 1);

    expect(profile.blending).toBe(THREE.NormalBlending);
    expect(profile.depthWrite).toBe(false);
    expect(profile.depthTest).toBe(true);
    expect(profile.alphaTest).toBe(0);
    expect(profile.size).toBeCloseTo(0.016);
    expect(profile.opacity).toBe(0.75);
    expect(profile.useSoftTexture).toBe(true);
  });

  it('keeps normal points opaque and unscaled', () => {
    const profile = getPointMaterialProfile('points', 0.004, 0.6);

    expect(profile.size).toBe(0.004);
    expect(profile.opacity).toBe(0.6);
    expect(profile.useSoftTexture).toBe(false);
  });

  it('normalizes mesh presentation for dark scenes', () => {
    const material = createPresentationMaterial(true);

    expect(material.metalness).toBe(0);
    expect(material.roughness).toBeCloseTo(0.82);
    expect(material.side).toBe(THREE.DoubleSide);
    expect(material.vertexColors).toBe(true);
    expect(material.transparent).toBe(false);
    material.dispose();
  });

  it('uses white base color for textured mesh presentation', () => {
    const map = new THREE.Texture();
    const material = createPresentationMaterial(false, map);

    expect(material.color.getHex()).toBe(0xffffff);
    expect(material.map).toBe(map);
    material.dispose();
    map.dispose();
  });

  it('removes coplanar triangulation diagonals from structure edges', () => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([
      0, 0, 0,
      1, 0, 0,
      1, 1, 0,
      0, 1, 0,
    ], 3));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);

    const edges = new THREE.EdgesGeometry(geometry, 30);

    expect(edges.getAttribute('position').count / 2).toBe(4);
    edges.dispose();
    geometry.dispose();
  });

  it('creates stable point colors without mutating RGB source data', () => {
    const positions = new Float32Array([0, 0, 0, 0, 1, 2]);
    const rgb = new Float32Array([0.2, 0.3, 0.4, 0.5, 0.6, 0.7]);

    const height = createPointColors('height', positions, rgb);
    const restored = createPointColors('rgb', positions, rgb);

    expect(Array.from(height)).toEqual(expect.arrayContaining([
      expect.closeTo(0.05, 5),
      expect.closeTo(0.8, 5),
      expect.closeTo(0.95, 5),
      expect.closeTo(0.95, 5),
      expect.closeTo(0.1, 5),
      expect.closeTo(0.1, 5),
    ]));
    expect(Array.from(restored)).toEqual(Array.from(rgb));
    expect(restored).not.toBe(rgb);
  });

  it('does not decode artifact-v2 linear colors twice', () => {
    expect(decodeArtifactColor(0.5, true)).toBe(0.5);
    expect(decodeArtifactColor(0.5, false)).toBeCloseTo(0.214041, 5);
  });

  it('round-trips legacy sRGB vertex colors', () => {
    const linear = srgbToLinear(0.5);

    expect(linear).toBeCloseTo(0.214041, 5);
    expect(linearToSrgb(linear)).toBeCloseTo(0.5, 5);
  });
});
