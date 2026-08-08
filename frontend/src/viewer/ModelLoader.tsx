import { useEffect, useState } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
}

export default function ModelLoader({ url, pointSize }: Props) {
  const { scene } = useGLTF(url);
  const [merged, setMerged] = useState<THREE.Points | null>(null);

  useEffect(() => {
    const allGeos: { geo: THREE.BufferGeometry }[] = [];
    scene.traverse((child) => {
      if (child instanceof THREE.Mesh && child.geometry) {
        allGeos.push({ geo: child.geometry });
      }
    });
    if (allGeos.length === 0) return;

    const positions: number[] = [];
    const colors: number[] = [];

    allGeos.forEach(({ geo }) => {
      const pos = geo.getAttribute('position');
      const col = geo.getAttribute('color');
      for (let i = 0; i < pos.count; i++) {
        positions.push(pos.getX(i), pos.getY(i), pos.getZ(i));
        colors.push(col ? col.getX(i) : 1, col ? col.getY(i) : 1, col ? col.getZ(i) : 1);
      }
    });

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    const mat = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      sizeAttenuation: true,
      depthWrite: true,
      blending: THREE.NormalBlending,
    });

    const pts = new THREE.Points(geo, mat);
    setMerged(pts);

    return () => { geo.dispose(); mat.dispose(); };
  }, [scene, pointSize]);

  if (!merged) return null;
  return <primitive object={merged} />;
}
