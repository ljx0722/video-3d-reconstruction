import { useMemo, useEffect, useRef } from 'react';
import * as THREE from 'three';

// Vertex shader: pass gaussian params to fragment
const vertShader = /* glsl */ `
  attribute float splatScale;
  attribute vec4 splatColor;
  varying vec4 vColor;
  varying float vScale;
  uniform float uPointSize;

  void main() {
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mvPosition;
    gl_PointSize = uPointSize * splatScale * (300.0 / -mvPosition.z);
    gl_PointSize = clamp(gl_PointSize, 0.5, 64.0);
    vColor = splatColor;
    vScale = splatScale;
  }
`;

// Fragment shader: radial gaussian falloff
const fragShader = /* glsl */ `
  varying vec4 vColor;
  varying float vScale;

  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    // Gaussian falloff: exp(-2 * d^2)
    float alpha = exp(-2.0 * d * d) * vColor.a;
    if (alpha < 0.01) discard;
    gl_FragColor = vec4(vColor.rgb, alpha);
  }
`;

interface Props {
  positions: Float32Array;
  colors: Float32Array;
  pointSize?: number;
}

export default function GaussianSplats({ positions, colors, pointSize = 1.0 }: Props) {
  const ref = useRef<THREE.Points>(null);
  const n = positions.length / 3;

  const { geo, mat } = useMemo(() => {
    // Downsample to max 500K points for real-time performance
    const maxPts = 500000;
    const step = n > maxPts ? Math.ceil(n / maxPts) : 1;
    const m = Math.floor(n / step);
    const posArr = new Float32Array(m * 3);
    const colArr4 = new Float32Array(m * 4);
    const scaleArr = new Float32Array(m);

    for (let i = 0; i < m; i++) {
      const si = i * step;
      const ti = i * 3;
      const qi = si * 3;
      posArr[ti] = positions[qi];
      posArr[ti+1] = positions[qi+1];
      posArr[ti+2] = positions[qi+2];
      colArr4[i*4] = colors[qi];
      colArr4[i*4+1] = colors[qi+1];
      colArr4[i*4+2] = colors[qi+2];
      colArr4[i*4+3] = 0.7;
    }

    // Estimate per-point scale from 8 random neighbors
    for (let i = 0; i < m; i++) {
      let minDist = Infinity;
      const ix = posArr[i*3], iy = posArr[i*3+1], iz = posArr[i*3+2];
      for (let j = 0; j < 8; j++) {
        const ri = Math.floor(Math.random() * m);
        if (ri === i) continue;
        const dx = ix - posArr[ri*3], dy = iy - posArr[ri*3+1], dz = iz - posArr[ri*3+2];
        const d2 = dx*dx + dy*dy + dz*dz;
        if (d2 < minDist && d2 > 0) minDist = d2;
      }
      scaleArr[i] = Math.sqrt(minDist < Infinity ? minDist : 0.01) * 2.5;
    }
    // Clamp within 0.2-5x of median
    const sorted = [...scaleArr].sort((a,b)=>a-b);
    const med = sorted[Math.floor(m/2)];
    for (let i=0;i<m;i++) scaleArr[i] = Math.max(med*0.2, Math.min(med*5, scaleArr[i]));

    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(posArr, 3));
    g.setAttribute('splatScale', new THREE.BufferAttribute(scaleArr, 1));
    g.setAttribute('splatColor', new THREE.BufferAttribute(colArr4, 4));
    const mat = new THREE.ShaderMaterial({
      vertexShader: vertShader, fragmentShader: fragShader,
      uniforms: { uPointSize: { value: pointSize } },
      transparent: true, depthWrite: false, blending: THREE.NormalBlending,
    });
    return { geo: g, mat };
  }, [positions, colors, n]);

  useEffect(() => {
    if (ref.current && mat) mat.uniforms.uPointSize.value = pointSize;
  }, [pointSize, mat]);

  if (n === 0) return null;
  return <points ref={ref} geometry={geo} material={mat} />;
}
