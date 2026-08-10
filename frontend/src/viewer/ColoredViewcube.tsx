import { useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';

const AXIS_FACES = [
  { axis: 'x', sign: 1,  label: '右', bg: '#ef4444' },
  { axis: 'x', sign: -1, label: '左', bg: '#ef4444' },
  { axis: 'y', sign: 1,  label: '上', bg: '#22c55e' },
  { axis: 'y', sign: -1, label: '下', bg: '#22c55e' },
  { axis: 'z', sign: 1,  label: '前', bg: '#3b82f6' },
  { axis: 'z', sign: -1, label: '后', bg: '#3b82f6' },
];

// Pre-render all textures once
const baseTextures = AXIS_FACES.map(f => {
  const sz = 128;
  const c = document.createElement('canvas');
  c.width = c.height = sz;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = f.bg;
  ctx.fillRect(0, 0, sz, sz);
  ctx.strokeStyle = 'rgba(0,0,0,0.3)';
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, sz - 4, sz - 4);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 56px "Inter", "Microsoft YaHei", "PingFang SC", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(f.label, sz / 2, sz / 2 + 4);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
});

// Pre-render hover textures
const hoverTextures = AXIS_FACES.map(f => {
  const sz = 128;
  const c = document.createElement('canvas');
  c.width = c.height = sz;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, sz, sz);
  ctx.strokeStyle = f.bg;
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, sz - 4, sz - 4);
  ctx.fillStyle = f.bg;
  ctx.font = 'bold 56px "Inter", "Microsoft YaHei", "PingFang SC", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(f.label, sz / 2, sz / 2 + 4);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
});

export default function ColoredViewcube({ size = 1.0 }: { size?: number }) {
  const { camera, gl } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  // Static materials (never recreated)
  const mats = useMemo(() => baseTextures.map(tex =>
    new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: 0.95 })
  ), []);
  const hoverMats = useMemo(() => hoverTextures.map(tex =>
    new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: 0.95 })
  ), []);

  // Park in top-right corner, follow camera rotation only
  useFrame(() => {
    if (!groupRef.current) return;
    const el = gl.domElement;
    if (el.clientWidth === 0) return;
    const w = el.clientWidth, h = el.clientHeight;
    // Fixed screen position (top-right, 80px from edges)
    const sx = (w - 80) / w * 2 - 1;
    const sy = -(80 / h) * 2 + 1;
    const v = new THREE.Vector3(sx, sy, 0.5);
    v.unproject(camera);
    const dir = v.clone().sub(camera.position).normalize();
    groupRef.current.position.copy(camera.position).add(dir.multiplyScalar(2.0));
    // Copy inverse camera orientation
    groupRef.current.quaternion.copy(camera.quaternion).invert();
  });

  const handleClick = (faceIdx: number) => {
    const f = AXIS_FACES[faceIdx];
    const dir = new THREE.Vector3();
    if (f.axis === 'x') dir.set(f.sign, 0, 0);
    else if (f.axis === 'y') dir.set(0, f.sign, 0);
    else dir.set(0, 0, f.sign);
    window.dispatchEvent(new CustomEvent('view-preset', { detail: { pos: dir.toArray() as [number,number,number] } }));
  };

  return (
    <group ref={groupRef}>
      {AXIS_FACES.map(({ axis, sign }, i) => {
        const pos: [number, number, number] = [
          axis === 'x' ? sign * size / 2 : 0,
          axis === 'y' ? sign * size / 2 : 0,
          axis === 'z' ? sign * size / 2 : 0,
        ];
        const rot: [number, number, number] = [
          axis === 'x' ? 0 : (axis === 'y' ? -Math.PI / 2 : axis === 'z' ? 0 : 0),
          (axis === 'x' ? Math.PI / 2 : 0),
          (axis === 'z' ? 0 : 0),
        ];
        return (
          <mesh key={i} position={pos} rotation={rot}
            onClick={(e) => { e.stopPropagation(); handleClick(i); }}
            onPointerEnter={() => setHovered(i)}
            onPointerLeave={() => setHovered(null)}
          >
            <planeGeometry args={[size * 0.92, size * 0.92]} />
            <primitive object={hovered === i ? hoverMats[i] : mats[i]} attach="material" />
          </mesh>
        );
      })}
      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(size, size, size)]} />
        <lineBasicMaterial color="rgba(255,255,255,0.4)" transparent depthTest={false} />
      </lineSegments>
    </group>
  );
}
