import { Suspense, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Grid } from '@react-three/drei';
import { getResultUrl } from '../api/client';
import ModelLoader from './ModelLoader';

interface Props {
  jobId: string;
}

export default function ViewerCanvas({ jobId }: Props) {
  const [pointSize, setPointSize] = useState(0.005);

  return (
    <Canvas className="!absolute inset-0" gl={{ preserveDrawingBuffer: true }}>
      <PerspectiveCamera makeDefault position={[5, 3, 5]} fov={60} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 10, 5]} intensity={0.3} />

      <Suspense fallback={null}>
        <ModelLoader url={getResultUrl(jobId)} pointSize={pointSize} />
      </Suspense>

      <Grid infiniteGrid fadeDistance={50} fadeStrength={5} sectionSize={1} cellSize={0.5} />
      <OrbitControls enableDamping dampingFactor={0.1} minDistance={0.5} maxDistance={50} />
    </Canvas>
  );
}
