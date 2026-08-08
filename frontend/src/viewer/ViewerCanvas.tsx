import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport } from '@react-three/drei';
import * as THREE from 'three';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';
import type { ClipPlane, BoxClip } from './Toolbar';

interface Props {
  jobId: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points) => void;
  clipPlanes?: ClipPlane[];
  boxClip?: BoxClip;
  showAxes?: boolean;
  bgColor?: 'dark' | 'light';
}

function ClippingPlanes3D({ clipPlanes, boxClip }: { clipPlanes: ClipPlane[]; boxClip: BoxClip }) {
  // Plane visualizers
  const activePlanes = clipPlanes.filter(p => p.enabled);

  // Build box clip geometry
  let boxGeom: THREE.BoxGeometry | null = null;
  if (boxClip.enabled) {
    const size = [
      boxClip.max[0] - boxClip.min[0],
      boxClip.max[1] - boxClip.min[1],
      boxClip.max[2] - boxClip.min[2],
    ];
    const center = [
      (boxClip.max[0] + boxClip.min[0]) / 2,
      (boxClip.max[1] + boxClip.min[1]) / 2,
      (boxClip.max[2] + boxClip.min[2]) / 2,
    ];
    boxGeom = new THREE.BoxGeometry(size[0], size[1], size[2]);
    boxGeom.translate(center[0], center[1], center[2]);
  }

  return (
    <group>
      {/* Plane visualizers */}
      {activePlanes.map((p, i) => {
        const size = 5;
        const pos = [0, 0, 0] as [number, number, number];
        const rot = p.axis === 'x' ? [0, 0, Math.PI / 2] : p.axis === 'y' ? [0, 0, 0] : [Math.PI / 2, 0, 0];
        if (p.axis === 'x') pos[0] = p.offset;
        if (p.axis === 'y') pos[1] = p.offset;
        if (p.axis === 'z') pos[2] = p.offset;
        return (
          <mesh key={`plane-${i}`} position={pos as any} rotation={rot as any}>
            <planeGeometry args={[size, size]} />
            <meshBasicMaterial color="#22c55e" transparent opacity={0.15} side={THREE.DoubleSide} />
          </mesh>
        );
      })}

      {/* Box clip wireframe */}
      {boxClip.enabled && boxGeom && (
        <lineSegments>
          <edgesGeometry args={[boxGeom]} />
          <lineBasicMaterial color="#22c55e" linewidth={1} transparent opacity={0.6} />
        </lineSegments>
      )}
    </group>
  );
}

function AxesHelper() {
  return (
    <group>
      {/* X - Red */}
      <mesh position={[1.5, 0, 0]}>
        <boxGeometry args={[3, 0.02, 0.02]} />
        <meshBasicMaterial color="#ef4444" />
      </mesh>
      {/* Y - Green */}
      <mesh position={[0, 1.5, 0]}>
        <boxGeometry args={[0.02, 3, 0.02]} />
        <meshBasicMaterial color="#22c55e" />
      </mesh>
      {/* Z - Blue */}
      <mesh position={[0, 0, 1.5]}>
        <boxGeometry args={[0.02, 0.02, 3]} />
        <meshBasicMaterial color="#3b82f6" />
      </mesh>
    </group>
  );
}

export default function ViewerCanvas({
  jobId, pointSize, opacity = 1, onPointsReady,
  clipPlanes, boxClip, showAxes, bgColor = 'dark',
}: Props) {
  const defaultClipPlanes: ClipPlane[] = clipPlanes || [
    { axis: 'x', offset: -1.5, enabled: false, negative: false },
    { axis: 'x', offset: 1.5, enabled: false, negative: true },
    { axis: 'y', offset: -1, enabled: false, negative: false },
    { axis: 'y', offset: 1, enabled: false, negative: true },
    { axis: 'z', offset: -1, enabled: false, negative: false },
    { axis: 'z', offset: 1, enabled: false, negative: true },
  ];
  const activeClipPlanes = clipPlanes || defaultClipPlanes;
  const defaultBoxClip: BoxClip = boxClip || { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };
  const activeBoxClip = boxClip || defaultBoxClip;

  // Build THREE clipping planes for actual rendering
  const threeClipPlanes: THREE.Plane[] = [];
  activeClipPlanes.filter(p => p.enabled).forEach(p => {
    const normal = new THREE.Vector3();
    if (p.axis === 'x') normal.set(1, 0, 0);
    if (p.axis === 'y') normal.set(0, 1, 0);
    if (p.axis === 'z') normal.set(0, 0, 1);
    if (p.negative) normal.negate();
    threeClipPlanes.push(new THREE.Plane(normal, Math.abs(p.offset)));
  });

  return (
    <Canvas
      className="!absolute inset-0"
      gl={{ preserveDrawingBuffer: true, antialias: true, localClippingEnabled: true }}
      camera={{ position: [2, 1, 3], fov: 50 }}
      style={{ background: bgColor === 'dark' ? '#0a0a0f' : '#e5e5e5' }}
    >
      <ambientLight intensity={bgColor === 'dark' ? 0.6 : 0.8} />
      <directionalLight position={[5, 5, 5]} intensity={bgColor === 'dark' ? 0.4 : 0.6} />

      <Suspense fallback={null}>
        <ModelLoader
          url={getResultUrl(jobId)}
          pointSize={pointSize}
          opacity={opacity}
          onPointsReady={onPointsReady}
          clipPlanes={threeClipPlanes}
        />
      </Suspense>

      {/* Visual guides for clipping planes */}
      <ClippingPlanes3D clipPlanes={activeClipPlanes} boxClip={activeBoxClip} />

      {/* Axis helper */}
      {showAxes && <AxesHelper />}

      {/* Orientation Cube */}
      <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
        <GizmoViewport axisColors={['#ef4444', '#22c55e', '#3b82f6']} labelColor="#9ca3af" />
      </GizmoHelper>

      <OrbitControls enableDamping dampingFactor={0.08} minDistance={0.2} maxDistance={20} target={[0, 0, 0]} />
    </Canvas>
  );
}
