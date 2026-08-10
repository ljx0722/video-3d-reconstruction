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

function makeFaceTexture(text: string, bg: string, hover: boolean): THREE.CanvasTexture {
  const sz = 128;
  const c = document.createElement('canvas');
  c.width = c.height = sz;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = hover ? '#fff' : bg;
  ctx.fillRect(0, 0, sz, sz);
  ctx.strokeStyle = hover ? bg : 'rgba(0,0,0,0.3)';
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, sz - 4, sz - 4);
  ctx.fillStyle = hover ? bg : '#ffffff';
  ctx.font = 'bold 56px "Inter", "Microsoft YaHei", "PingFang SC", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, sz / 2, sz / 2 + 4);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
}

export default function ColoredViewcube({ size = 1.0 }: { size?: number }) {
  const { camera, gl } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  const materials = useMemo(() =>
    AXIS_FACES.map((f, i) =>
      new THREE.MeshBasicMaterial({ map: makeFaceTexture(f.label, f.bg, hovered === i), side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: 0.95 })
    ), [hovered]);

  // Position in top-right corner of screen, orientation inverse of main camera
  useFrame(() => {
    if (!groupRef.current) return;
    const el = gl.domElement;
    const w = el.clientWidth, h = el.clientHeight;
    // Place at world-space position that maps to screen-space (w-100, 100)
    const sPos = new THREE.Vector2(w - 100, 100);
    const worldBase = new THREE.Vector3(sPos.x / w * 2 - 1, -(sPos.y / h) * 2 + 1, 0.5);
    worldBase.unproject(camera);
    const dirToBase = worldBase.clone().sub(camera.position).normalize();
    const worldPos = camera.position.clone().add(dirToBase.multiplyScalar(2.0));
    groupRef.current.position.copy(worldPos);
    // Orient to match camera
    groupRef.current.quaternion.copy(camera.quaternion).invert();
  });

  const handleClick = (faceIdx: number) => {
    const f = AXIS_FACES[faceIdx];
    const dir = new THREE.Vector3();
    if (f.axis === 'x') dir.set(f.sign, 0, 0);
    else if (f.axis === 'y') dir.set(0, f.sign, 0);
    else dir.set(0, 0, f.sign);
    const target = new THREE.Vector3(0, 0, 0);
    const dist = camera.position.length();
    camera.position.copy(target.clone().add(dir.clone().multiplyScalar(dist)));
    camera.lookAt(target);
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
          <mesh key={i}
            position={pos}
            rotation={rot}
            onClick={(e) => { e.stopPropagation(); handleClick(i); }}
            onPointerEnter={() => setHovered(i)}
            onPointerLeave={() => setHovered(null)}
          >
            <planeGeometry args={[size * 0.92, size * 0.92]} />
            <primitive object={materials[i]} attach="material" />
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
