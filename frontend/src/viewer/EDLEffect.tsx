import { EffectComposer, Bloom, BrightnessContrast, Noise } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';

interface EDLProps {
  edlStrength?: number;
}

export default function EDLEffect({ edlStrength = 0.4 }: EDLProps) {
  return (
    <EffectComposer enabled multisampling={0}>
      {/* Bloom for specular highlights (Potree-like glow) */}
      <Bloom
        luminanceThreshold={0.2}
        luminanceSmoothing={0.9}
        intensity={edlStrength * 0.6}
        mipmapBlur
      />

      {/* Contrast boost for edge definition */}
      <BrightnessContrast
        brightness={0.02}
        contrast={0.15 + edlStrength * 0.1}
        blendFunction={BlendFunction.NORMAL}
      />

      {/* Subtle noise dithering to break up flat color bands */}
      <Noise premultiply blendFunction={BlendFunction.SRC} opacity={0.008} />
    </EffectComposer>
  );
}
