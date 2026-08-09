import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface Props {
  pointSize: number;
  opacity?: number;
  clipPlanes?: THREE.Plane[];
  splatMode?: boolean;
  streamBuffer?: Float32Array | null;
  streamAppend?: boolean;
  onPointsReady?: (mesh: THREE.Points, count: number) => void;
}

export default function StreamLoader({ pointSize, opacity = 1, clipPlanes, splatMode, streamBuffer, streamAppend, onPointsReady }: Props) {
  const pointsRef = useRef<THREE.Points | null>(null);
  const totalCount = useRef(0);
  const [mesh, setMesh] = useState<THREE.Points | null>(null);

  // Create initial empty points when first buffer arrives
  useEffect(() => {
    if (!streamBuffer || streamBuffer.length < 6) return;

    if (streamAppend && pointsRef.current) {
      const geo = pointsRef.current.geometry;
      const posAttr = geo.getAttribute('position') as THREE.BufferAttribute;
      const colAttr = geo.getAttribute('color') as THREE.BufferAttribute;
      const nExist = posAttr.count;
      const nNew = Math.floor(streamBuffer.length / 6);
      const newPos = new Float32Array((nExist + nNew) * 3);
      const newCol = new Float32Array((nExist + nNew) * 3);
      newPos.set(posAttr.array as Float32Array, 0);
      newCol.set(colAttr.array as Float32Array, 0);
      for (let i = 0; i < nNew; i++) {
        const b = i * 6;
        const t = (nExist + i) * 3;
        newPos[t] = streamBuffer[b]; newPos[t+1] = streamBuffer[b+1]; newPos[t+2] = streamBuffer[b+2];
        newCol[t] = streamBuffer[b+3]; newCol[t+1] = streamBuffer[b+4]; newCol[t+2] = streamBuffer[b+5];
      }
      geo.setAttribute('position', new THREE.BufferAttribute(newPos, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(newCol, 3));
      geo.attributes.position.needsUpdate = true;
      geo.attributes.color.needsUpdate = true;
      geo.setDrawRange(0, nExist + nNew);
      totalCount.current = nExist + nNew;
      if (onPointsReady) onPointsReady(pointsRef.current, totalCount.current);
    } else {
      const n = Math.floor(streamBuffer.length / 6);
      const pos = new Float32Array(n * 3);
      const col = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        pos[i*3]=streamBuffer[i*6]; pos[i*3+1]=streamBuffer[i*6+1]; pos[i*3+2]=streamBuffer[i*6+2];
        col[i*3]=streamBuffer[i*6+3]; col[i*3+1]=streamBuffer[i*6+4]; col[i*3+2]=streamBuffer[i*6+5];
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      const mat = new THREE.PointsMaterial({
        size: pointSize * 2, vertexColors: true, sizeAttenuation: true,
        depthWrite: false, blending: THREE.NormalBlending,
        transparent: true, opacity: 0.85, depthTest: true,
      });
      const pts = new THREE.Points(geo, mat);
      pointsRef.current = pts;
      totalCount.current = n;
      setMesh(pts);
      if (onPointsReady) onPointsReady(pts, n);
    }
  }, [streamBuffer, streamAppend]);

  // Update material properties
  useEffect(() => {
    const m = pointsRef.current?.material as THREE.PointsMaterial;
    if (!m) return;
    m.size = splatMode ? pointSize * 4 : pointSize;
  }, [pointSize, splatMode]);

  useEffect(() => {
    const m = pointsRef.current?.material as THREE.PointsMaterial;
    if (m) m.opacity = opacity;
  }, [opacity]);

  useEffect(() => {
    const m = pointsRef.current?.material as THREE.PointsMaterial;
    if (m) m.clippingPlanes = clipPlanes || [];
  }, [clipPlanes]);

  if (!mesh) return null;
  return <primitive object={mesh} />;
}
