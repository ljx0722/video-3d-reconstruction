import { EffectComposer, Bloom, ToneMapping } from '@react-three/postprocessing';
import { BlendFunction, ToneMappingMode } from 'postprocessing';

interface BloomEffectProps {
  bloomStrength?: number;
  bloomThreshold?: number;
  bloomSmoothing?: number;
}

export default function BloomEffect({ bloomStrength = 0, bloomThreshold = 0.9, bloomSmoothing = 0.05 }: BloomEffectProps) {
  if (bloomStrength <= 0.01) return null;

  return (
    <EffectComposer enabled multisampling={0}>
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Bloom
        luminanceThreshold={bloomThreshold}
        luminanceSmoothing={bloomSmoothing}
        intensity={bloomStrength}
        mipmapBlur={false}
        blendFunction={BlendFunction.SCREEN}
      />
    </EffectComposer>
  );
}
