import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport, Grid } from '@react-three/drei';
import * as THREE from 'three';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';
import type { BoxClip } from './Toolbar';

interface Props {
  jobId: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points) => void;
  boxClip?: BoxClip;
  showAxes?: boolean;
  orthographic?: boolean;
  splatMode?: boolean;
  showGrid?: boolean;
}

function BoxWireframe({ boxClip }: { boxClip: BoxClip }) {
  if (!boxClip.enabled) return null;
  const size: [number,number,number] = [
    boxClip.max[0]-boxClip.min[0],
    boxClip.max[1]-boxClip.min[1],
    boxClip.max[2]-boxClip.min[2],
  ];
  const center: [number,number,number] = [
    (boxClip.max[0]+boxClip.min[0])/2,
    (boxClip.max[1]+boxClip.min[1])/2,
    (boxClip.max[2]+boxClip.min[2])/2,
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
  boxClip, showAxes, orthographic, splatMode, showGrid,
}: Props) {
  const defaultBox: BoxClip = boxClip || { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };
  const activeBox = boxClip || defaultBox;

  // Build THREE clipping planes from box bounds
  const threeClipPlanes: THREE.Plane[] = [];
  if (activeBox.enabled) {
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 1, 0, 0), -activeBox.min[0])); // +X min
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3(-1, 0, 0),  activeBox.max[0])); // -X max
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0, 1, 0), -activeBox.min[1])); // +Y min
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,-1, 0),  activeBox.max[1])); // -Y max
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0, 0, 1), -activeBox.min[2])); // +Z min
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0, 0,-1),  activeBox.max[2])); // -Z max
  }

  return (
    <Canvas
      key={orthographic ? 'ortho' : 'persp'}
      className="!absolute inset-0"
      gl={{ preserveDrawingBuffer: true, antialias: true, localClippingEnabled: true }}
      orthographic={orthographic}
      camera={orthographic
        ? { position: [2, 1, 3], zoom: 80, near: 0.1, far: 200 }
        : { position: [2, 1, 3], fov: 50 }}
      style={{ background: '#0a0a0f' }}
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={null}>
        <ModelLoader
          url={getResultUrl(jobId)}
          pointSize={pointSize}
          opacity={opacity}
          onPointsReady={onPointsReady}
          clipPlanes={threeClipPlanes}
          splatMode={splatMode}
        />
      </Suspense>

      {/* Visual guides for clipping planes */}
      <BoxWireframe boxClip={activeBox} />

      {/* Grid */}
      {showGrid && <Grid infiniteGrid fadeDistance={50} fadeStrength={5} sectionSize={1} cellSize={0.5} sectionColor="#374151" cellColor="#1f2937" />}

      {/* Axis helper */}
      {showAxes && <AxesHelper />}

      {/* Orientation Cube - top right */}
      <GizmoHelper alignment="top-right" margin={[80, 80]}>
        <GizmoViewport axisColors={['#ef4444', '#22c55e', '#3b82f6']} labelColor="#9ca3af" />
      </GizmoHelper>

      <OrbitControls
        enableDamping dampingFactor={0.08}
        minDistance={0.05} maxDistance={200}
        minPolarAngle={0} maxPolarAngle={Math.PI}
        minAzimuthAngle={-Infinity} maxAzimuthAngle={Infinity}
        target={[0, 0, 0]}
      />
    </Canvas>
  );
}
