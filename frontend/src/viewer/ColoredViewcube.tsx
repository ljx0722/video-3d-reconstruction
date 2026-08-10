import { useRef, useState } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';

const FACES = [
  { axis: 'x', sign: 1,  label: '右', bg: '#ef4444' },
  { axis: 'x', sign: -1, label: '左', bg: '#ef4444' },
  { axis: 'y', sign: 1,  label: '上', bg: '#22c55e' },
  { axis: 'y', sign: -1, label: '下', bg: '#22c55e' },
  { axis: 'z', sign: 1,  label: '前', bg: '#3b82f6' },
  { axis: 'z', sign: -1, label: '后', bg: '#3b82f6' },
];

function buildTexture(label: string, bg: string, hover: boolean): THREE.CanvasTexture {
  const s = 128;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const ctx = c.getContext('2d')!;
  if (hover) {
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = bg; ctx.fillStyle = bg;
  } else {
    ctx.fillStyle = bg; ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = 'rgba(0,0,0,0.3)'; ctx.fillStyle = '#ffffff';
  }
  ctx.lineWidth = 4; ctx.strokeRect(2, 2, s - 4, s - 4);
  ctx.font = 'bold 56px "Inter", "Microsoft YaHei", "PingFang SC", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(label, s / 2, s / 2 + 4);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter;
  return t;
}

function buildMaterials() {
  const mats: THREE.MeshBasicMaterial[] = [];
  const hoverMats: THREE.MeshBasicMaterial[] = [];
  for (let i = 0; i < FACES.length; i++) {
    const f = FACES[i];
    mats.push(new THREE.MeshBasicMaterial({
      map: buildTexture(f.label, f.bg, false),
      side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: 0.95,
    }));
    hoverMats.push(new THREE.MeshBasicMaterial({
      map: buildTexture(f.label, f.bg, true),
      side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: 0.95,
    }));
  }
  return { mats, hoverMats };
}

// Set renderOrder via ref callback (runs as soon as DOM node is created, before useFrame)
function setHiOrder(el: any) {
  if (el) el.renderOrder = 999;
}

export default function ColoredViewcube({ size = 1.0 }: { size?: number }) {
  const { camera, gl } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [matSets] = useState(() => buildMaterials());

  useFrame(() => {
    if (!groupRef.current) return;
    const el = gl.domElement;
    if (el.clientWidth === 0) return;
    const w = el.clientWidth, h = el.clientHeight;
    const sx = (w - 80) / w * 2 - 1;
    const sy = -(80 / h) * 2 + 1;
    const v = new THREE.Vector3(sx, sy, 0.5);
    v.unproject(camera);
    const dir = v.clone().sub(camera.position).normalize();
    // Always park at a safe distance in front of camera, but min 0.8 to avoid near-plane clip
    const dist = Math.max(0.8, camera.position.length() * 0.1);
    groupRef.current.position.copy(camera.position).add(dir.multiplyScalar(dist));
    groupRef.current.quaternion.copy(camera.quaternion).invert();
  });

  const onClick = (i: number) => (e: any) => {
    e.stopPropagation();
    const f = FACES[i];
    const dir = new THREE.Vector3();
    if (f.axis === 'x') dir.set(f.sign, 0, 0);
    else if (f.axis === 'y') dir.set(0, f.sign, 0);
    else dir.set(0, 0, f.sign);
    window.dispatchEvent(new CustomEvent('view-preset', { detail: { pos: dir.toArray() as [number,number,number] } }));
  };

  return (
    <group ref={groupRef}>
      {FACES.map((f, i) => {
        const pos: [number,number,number] = [
          f.axis === 'x' ? f.sign * size / 2 : 0,
          f.axis === 'y' ? f.sign * size / 2 : 0,
          f.axis === 'z' ? f.sign * size / 2 : 0,
        ];
        const rot: [number,number,number] = [
          f.axis === 'x' ? 0 : (f.axis === 'y' ? -Math.PI / 2 : 0),
          (f.axis === 'x' ? Math.PI / 2 : 0), 0,
        ];
        return (
          <mesh key={i} position={pos} rotation={rot} ref={setHiOrder}
            onClick={onClick(i)}
            onPointerEnter={() => setHovered(i)}
            onPointerLeave={() => setHovered(null)}
          >
            <planeGeometry args={[size * 0.92, size * 0.92]} />
            <primitive object={hovered === i ? matSets.hoverMats[i] : matSets.mats[i]} attach="material" />
          </mesh>
        );
      })}
      <lineSegments ref={setHiOrder}>
        <edgesGeometry args={[new THREE.BoxGeometry(size, size, size)]} />
        <lineBasicMaterial color="rgba(255,255,255,0.4)" transparent depthTest={false} />
      </lineSegments>
    </group>
  );
}
