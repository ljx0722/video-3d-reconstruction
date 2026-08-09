import { useMemo, useEffect, useState } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points, count: number) => void;
  onCameraPositions?: (positions: Float32Array) => void;
  clipPlanes?: THREE.Plane[];
  splatMode?: boolean;
}

export default function ModelLoader({ url, pointSize, opacity = 1, onPointsReady, onCameraPositions, clipPlanes, splatMode }: Props) {
  const { scene } = useGLTF(url);
  const [splatTex] = useState(() => {
    const c = document.createElement('canvas');
    c.width = c.height = 32;
    const ctx = c.getContext('2d')!;
    const g = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.4, 'rgba(255,255,255,0.6)');
    g.addColorStop(0.8, 'rgba(255,255,255,0.1)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 32, 32);
    return new THREE.CanvasTexture(c);
  });

  const points = useMemo(() => {
    const pcPos: number[] = [];
    const pcCol: number[] = [];
    const camPos: number[] = [];

    scene.traverse((child: any) => {
      const geo = child.geometry as THREE.BufferGeometry | undefined;
      if (!geo || !geo.getAttribute) return;
      const pos = geo.getAttribute('position');
      const col = geo.getAttribute('color');
      if (!pos) return;
      if (pos.count < 50) {
        let cx=0,cy=0,cz=0;
        for (let i=0; i<pos.count; i++) { cx+=pos.getX(i); cy+=pos.getY(i); cz+=pos.getZ(i); }
        camPos.push(cx/pos.count, cy/pos.count, cz/pos.count);
      } else {
        for (let i=0; i<pos.count; i++) {
          pcPos.push(pos.getX(i), pos.getY(i), pos.getZ(i));
          pcCol.push(col ? col.getX(i) : 1, col ? col.getY(i) : 1, col ? col.getZ(i) : 1);
        }
      }
    });

    if (camPos.length > 0 && onCameraPositions) onCameraPositions(new Float32Array(camPos));
    if (pcPos.length === 0) return null;

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pcPos), 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pcCol), 3));

    const mat = new THREE.PointsMaterial({
      size: splatMode ? pointSize * 4 : pointSize, vertexColors: true, sizeAttenuation: true,
      depthWrite: splatMode ? false : true,
      blending: splatMode ? THREE.AdditiveBlending : THREE.NormalBlending,
      transparent: true, opacity, clippingPlanes: clipPlanes || [], clipShadows: true,
      map: splatMode ? splatTex : null, depthTest: true,
    });
    return new THREE.Points(geo, mat);
  }, [scene]);

  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).size = splatMode ? pointSize * 4 : pointSize; }, [pointSize, points, splatMode]);
  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).opacity = opacity; }, [opacity, points]);
  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).clippingPlanes = clipPlanes || []; }, [clipPlanes, points]);

  useEffect(() => {
    if (points && onPointsReady) {
      const pos = points.geometry.getAttribute('position');
      onPointsReady(points, pos ? pos.count : 0);
    }
  }, [points, onPointsReady]);

  if (!points) return null;
  return <primitive object={points} />;
}
