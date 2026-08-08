import { useMemo, useEffect } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
  onPointsReady?: (mesh: THREE.Points) => void;
}

export default function ModelLoader({ url, pointSize, onPointsReady }: Props) {
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

    const posArr = new Float32Array(positions);
    const colArr = new Float32Array(colors);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(posArr, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3));

    const mat = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      sizeAttenuation: true,
      depthWrite: true,
      blending: THREE.NormalBlending,
    });

    return new THREE.Points(geo, mat);
  }, [scene]);

  // Adjust point size
  useEffect(() => {
    if (points) {
      (points.material as THREE.PointsMaterial).size = pointSize;
    }
  }, [pointSize, points]);

  // Notify parent
  useEffect(() => {
    if (points && onPointsReady) onPointsReady(points);
  }, [points, onPointsReady]);

  if (!points) return null;
  return <primitive object={points} />;
}
