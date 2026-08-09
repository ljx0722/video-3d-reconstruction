import { Suspense, useState, useCallback, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { TrackballControls, GizmoHelper, GizmoViewport, Grid, Html, Line, OrthographicCamera, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';
import StreamLoader from './StreamLoader';
import EDLEffect from './EDLEffect';
import type { BoxClip } from './Toolbar';

interface Props {
  jobId: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points, count?: number) => void;
  boxClip?: BoxClip;
  showAxes?: boolean;
  orthographic?: boolean;
  splatMode?: boolean;
  showGrid?: boolean;
  showTrajectory?: boolean;
  edlStrength?: number;
  streamBuffer?: Float32Array | null;
  streamAppend?: boolean;
  liveMode?: boolean;
}

function BoxWireframe({ boxClip }: { boxClip: BoxClip }) {
  if (!boxClip.enabled) return null;
  const size: [number,number,number] = [
    boxClip.max[0]-boxClip.min[0], boxClip.max[1]-boxClip.min[1], boxClip.max[2]-boxClip.min[2],
  ];
  const center: [number,number,number] = [
    (boxClip.max[0]+boxClip.min[0])/2, (boxClip.max[1]+boxClip.min[1])/2, (boxClip.max[2]+boxClip.min[2])/2,
  ];
  const geom = new THREE.BoxGeometry(size[0], size[1], size[2]);
  geom.translate(center[0], center[1], center[2]);
  return (
    <lineSegments>
      <edgesGeometry args={[geom]} />
      <lineBasicMaterial color="#22c55e" transparent opacity={0.7} depthTest={true} />
    </lineSegments>
  );
}

function CameraTrail({ positions }: { positions: Float32Array }) {
  const n = positions.length / 3;
  if (n < 2) return null;

  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < n; i++) {
    pts.push(new THREE.Vector3(positions[i*3], positions[i*3+1], positions[i*3+2]));
  }

  const sorted: THREE.Vector3[] = [pts[0]];
  const remaining = new Set(pts.slice(1).map((_, i) => i + 1));
  while (remaining.size > 0) {
    const last = sorted[sorted.length - 1];
    let bestIdx = -1;
    let bestDist = Infinity;
    for (const idx of remaining) {
      const d = last.distanceToSquared(pts[idx]);
      if (d < bestDist) { bestDist = d; bestIdx = idx; }
    }
    sorted.push(pts[bestIdx]);
    remaining.delete(bestIdx);
  }

  const linePoints = sorted.map(p => [p.x, p.y, p.z] as [number, number, number]);

  const colors = sorted.map((_, i) => {
    const t = i / Math.max(1, sorted.length - 1);
    return [t, 0.2 + (1 - Math.abs(t - 0.5) * 2) * 0.4, 1 - t] as [number, number, number];
  });

  const center = sorted[Math.floor(sorted.length / 2)];

  return (
    <group>
      <Line points={linePoints} color="white" lineWidth={1.5} vertexColors={colors} />
      <Html position={[center.x, center.y + 0.3, center.z]} center>
        <div className="bg-gray-900/80 backdrop-blur px-2 py-0.5 rounded text-[10px] text-gray-400 whitespace-nowrap border border-gray-700 select-none">
          摄像机轨迹 · {n} 帧
        </div>
      </Html>
      <mesh position={sorted[0].toArray()}>
        <sphereGeometry args={[0.025, 8, 8]} />
        <meshBasicMaterial color="#3B82F6" />
      </mesh>
      <mesh position={sorted[sorted.length - 1].toArray()}>
        <sphereGeometry args={[0.025, 8, 8]} />
        <meshBasicMaterial color="#EF4444" />
      </mesh>
    </group>
  );
}

function AdaptiveControls() {
  const ref = useRef<any>(null);

  useFrame(({ camera }) => {
    if (ref.current) {
      const d = camera.position.length();
      ref.current.rotateSpeed = Math.max(1.5, Math.min(20, d * 2.5));
      ref.current.zoomSpeed = Math.max(0.5, Math.min(80, d * 6));
      ref.current.panSpeed = Math.max(0.3, Math.min(15, d * 1.2));
    }
  });

  return (
    <TrackballControls
      ref={ref}
      target={[0, 0, 0]}
    />
  );
}

function AxesHelper3D() {
  return (
    <group>
      <mesh position={[1.5, 0, 0]}><boxGeometry args={[3, 0.02, 0.02]} /><meshBasicMaterial color="#ef4444" /></mesh>
      <mesh position={[0, 1.5, 0]}><boxGeometry args={[0.02, 3, 0.02]} /><meshBasicMaterial color="#22c55e" /></mesh>
      <mesh position={[0, 0, 1.5]}><boxGeometry args={[0.02, 0.02, 3]} /><meshBasicMaterial color="#3b82f6" /></mesh>
    </group>
  );
}

export default function ViewerCanvas({
  jobId, pointSize, opacity = 1, onPointsReady,
  boxClip, showAxes, orthographic, splatMode, showGrid, showTrajectory = true,
  edlStrength = 0.4, streamBuffer, streamAppend, liveMode,
}: Props) {
  const [camPositions, setCamPositions] = useState<Float32Array | null>(null);
  const defaultBox: BoxClip = boxClip || { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };
  const activeBox = boxClip || defaultBox;

  const handleCameras = useCallback((pos: Float32Array) => setCamPositions(pos), []);

  const threeClipPlanes: THREE.Plane[] = [];
  if (activeBox.enabled) {
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 1,0,0), -activeBox.min[0]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3(-1,0,0),  activeBox.max[0]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,1,0), -activeBox.min[1]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,-1,0), activeBox.max[1]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,0,1), -activeBox.min[2]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,0,-1),activeBox.max[2]));
  }

  return (
    <Canvas
      className="!absolute inset-0"
      gl={{ preserveDrawingBuffer: true, antialias: true, localClippingEnabled: true }}
      frameloop="always"
      style={{ background: '#0a0a0f' }}
    >
      <PerspectiveCamera makeDefault={!orthographic} position={[2, 1, 3]} fov={50} near={0.01} far={200} />
      <OrthographicCamera makeDefault={orthographic} position={[2, 1, 3]} zoom={80} near={0.01} far={200} />

      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={null}>
        {liveMode || streamBuffer ? (
          <StreamLoader
            pointSize={pointSize}
            opacity={opacity}
            onPointsReady={onPointsReady as any}
            clipPlanes={threeClipPlanes}
            splatMode={splatMode}
            streamBuffer={streamBuffer || undefined}
            streamAppend={streamAppend}
          />
        ) : (
          <ModelLoader
            url={getResultUrl(jobId)}
            pointSize={pointSize}
            opacity={opacity}
            onPointsReady={onPointsReady as any}
            onCameraPositions={handleCameras}
            clipPlanes={threeClipPlanes}
            splatMode={splatMode}
          />
        )}
      </Suspense>

      {camPositions && showTrajectory && <CameraTrail positions={camPositions} />}

      <BoxWireframe boxClip={activeBox} />

      {showGrid && <Grid infiniteGrid fadeDistance={50} fadeStrength={5} sectionSize={1} cellSize={0.5} sectionColor="#374151" cellColor="#1f2937" />}

      {showAxes && <AxesHelper3D />}

      <GizmoHelper alignment="top-right" margin={[60, 60]}>
        <GizmoViewport axisColors={['#ef4444', '#22c55e', '#3b82f6']} labelColor="#9ca3af" />
      </GizmoHelper>

      <AdaptiveControls />

      <EDLEffect edlStrength={edlStrength} />
    </Canvas>
  );
}
