import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';

interface Props {
  jobId: string;
  pointSize: number;
  onPointsReady?: (mesh: THREE.Points) => void;
}

export default function ViewerCanvas({ jobId, pointSize, onPointsReady }: Props) {
  return (
    <Canvas className="!absolute inset-0" gl={{ preserveDrawingBuffer: true, antialias: true }}
      camera={{ position: [2, 1, 3], fov: 50 }}>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={null}>
        <ModelLoader url={getResultUrl(jobId)} pointSize={pointSize} onPointsReady={onPointsReady} />
      </Suspense>

      <OrbitControls enableDamping dampingFactor={0.08} minDistance={0.2} maxDistance={20} target={[0, 0, 0]} />
    </Canvas>
  );
}
