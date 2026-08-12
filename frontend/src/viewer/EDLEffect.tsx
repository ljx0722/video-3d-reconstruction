import { EffectComposer, Bloom, ToneMapping } from '@react-three/postprocessing';
import { BlendFunction, ToneMappingMode } from 'postprocessing';

interface BloomEffectProps {
  bloomStrength?: number;
}

export default function BloomEffect({ bloomStrength = 0 }: BloomEffectProps) {
  if (bloomStrength <= 0.01) return null;

  return (
    <EffectComposer enabled multisampling={0}>
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Bloom
        luminanceThreshold={0.9}
        luminanceSmoothing={0.2}
        intensity={bloomStrength}
        mipmapBlur={false}
        blendFunction={BlendFunction.SCREEN}
      />
    </EffectComposer>
  );
}
