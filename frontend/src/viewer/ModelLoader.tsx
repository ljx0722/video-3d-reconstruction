import { useMemo } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
}

export default function ModelLoader({ url, pointSize }: Props) {
  const { scene } = useGLTF(url);

  const points = useMemo(() => {
    const positions: number[] = [];
    const colors: number[] = [];

    scene.traverse((child: any) => {
      const geo = child.geometry as THREE.BufferGeometry | undefined;
      if (!geo || !geo.getAttribute) return;
      const pos = geo.getAttribute('position');
      const col = geo.getAttribute('color');
      if (!pos) return;
      for (let i = 0; i < pos.count; i++) {
        positions.push(pos.getX(i), pos.getY(i), pos.getZ(i));
        colors.push(col ? col.getX(i) : 1, col ? col.getY(i) : 1, col ? col.getZ(i) : 1);
      }
    });

    if (positions.length === 0) return null;

    const mergedGeo = new THREE.BufferGeometry();
    mergedGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    mergedGeo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    const mat = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      sizeAttenuation: true,
      depthWrite: true,
      blending: THREE.NormalBlending,
    });

    return new THREE.Points(mergedGeo, mat);
  }, [scene, pointSize]);

  if (!points) return null;
  return <primitive object={points} />;
}
