import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
}

export default function ModelLoader({ url, pointSize }: Props) {
  const { scene } = useGLTF(url);

  return (
    <group>
      {scene.children.map((child, i) => {
        if (child instanceof THREE.Mesh && child.geometry) {
          const geo = child.geometry;
          const hasColors = geo.hasAttribute('color');
          return (
            <points key={i} geometry={geo}>
              <pointsMaterial
                size={pointSize}
                vertexColors={hasColors}
                color={hasColors ? undefined : '#ffffff'}
                sizeAttenuation
                depthWrite={false}
                blending={THREE.NormalBlending}
              />
            </points>
          );
        }
        return <primitive key={i} object={child} />;
      })}
    </group>
  );
}
