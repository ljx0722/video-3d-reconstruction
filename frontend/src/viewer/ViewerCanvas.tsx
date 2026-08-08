import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';

const POINT_SIZE = 0.008;

interface Props {
  jobId: string;
}

export default function ViewerCanvas({ jobId }: Props) {
  return (
    <Canvas className="!absolute inset-0" gl={{ preserveDrawingBuffer: true, antialias: true }}>
      <PerspectiveCamera makeDefault position={[2, 1, 3]} fov={50} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={null}>
        <ModelLoader url={getResultUrl(jobId)} pointSize={POINT_SIZE} />
      </Suspense>

      <OrbitControls
        enableDamping
        dampingFactor={0.08}
        minDistance={0.2}
        maxDistance={20}
        target={[0, 0, 0]}
      />
    </Canvas>
  );
}
