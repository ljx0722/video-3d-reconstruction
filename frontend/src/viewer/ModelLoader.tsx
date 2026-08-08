import { useMemo, useEffect } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points) => void;
  clipPlanes?: THREE.Plane[];
}

export default function ModelLoader({ url, pointSize, opacity = 1, onPointsReady, clipPlanes }: Props) {
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

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(colors), 3));

    const mat = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      sizeAttenuation: true,
      depthWrite: true,
      blending: THREE.NormalBlending,
      transparent: opacity < 1,
      opacity,
      clippingPlanes: clipPlanes || [],
      clipShadows: true,
    });

    return new THREE.Points(geo, mat);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene]);

  // Update point size
  useEffect(() => {
    if (points) {
      (points.material as THREE.PointsMaterial).size = pointSize;
    }
  }, [pointSize, points]);

  // Update opacity
  useEffect(() => {
    if (points) {
      const mat = points.material as THREE.PointsMaterial;
      mat.opacity = opacity;
      mat.transparent = opacity < 1;
    }
  }, [opacity, points]);

  // Update clipping planes
  useEffect(() => {
    if (points) {
      (points.material as THREE.PointsMaterial).clippingPlanes = clipPlanes || [];
    }
  }, [clipPlanes, points]);

  // Notify parent
  useEffect(() => {
    if (points && onPointsReady) {
      onPointsReady(points);
    }
  }, [points, onPointsReady]);

  if (!points) return null;
  return <primitive object={points} />;
}
