import { EffectComposer, Bloom } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';

interface EDLProps {
  edlStrength?: number;
}

export default function EDLEffect({ edlStrength = 0 }: EDLProps) {
  if (edlStrength <= 0.01) return null;

  return (
    <EffectComposer enabled multisampling={0}>
      <Bloom
        luminanceThreshold={0.4}
        luminanceSmoothing={0.7}
        intensity={edlStrength * 0.3}
        mipmapBlur={false}
        blendFunction={BlendFunction.SCREEN}
      />
    </EffectComposer>
  );
}
