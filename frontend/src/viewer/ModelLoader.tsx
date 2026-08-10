import { useMemo, useEffect, useState } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';

interface Props {
  url: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points, count: number) => void;
  onMeshReady?: (mesh: THREE.Group) => void;
  onCameraPositions?: (positions: Float32Array) => void;
  clipPlanes?: THREE.Plane[];
  splatMode?: boolean;
  viewMode?: 'points' | 'gaussian' | 'mesh' | 'wireframe';
}

export default function ModelLoader({ url, pointSize, opacity = 1, onPointsReady, onMeshReady, onCameraPositions, clipPlanes, splatMode, viewMode = 'points' }: Props) {
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

  const { points, meshes } = useMemo(() => {
    const pcPos: number[] = [];
    const pcCol: number[] = [];
    const camPos: number[] = [];
    const meshList: THREE.Mesh[] = [];

    try {
      if (scene) scene.traverse((child: any) => {
        // Skip non-standard children that might lack geometry
        if (!child || typeof child !== 'object') return;

        if (child.isMesh) {
          const geo = child.geometry as THREE.BufferGeometry | undefined;
          if (geo && geo.index) {
            meshList.push(child.clone());
          }
          return;
        }
        const geo = child.geometry as THREE.BufferGeometry | undefined;
        if (!geo || !geo.getAttribute) return;
        const pos = geo.getAttribute('position');
        const col = geo.getAttribute('color');
        if (!pos || pos.count === 0) return;
        if (pos.count < 50) {
          let cx = 0, cy = 0, cz = 0;
          try {
            for (let i = 0; i < pos.count; i++) { cx += pos.getX(i); cy += pos.getY(i); cz += pos.getZ(i); }
            camPos.push(cx / pos.count, cy / pos.count, cz / pos.count);
          } catch { /* skip corrupted camera geometry */ }
        } else {
          const total = pos.count;
          const budget = 2000000;
          const step = total > budget ? Math.ceil(total / budget) : 1;
          try {
            for (let i = 0; i < total; i += step) {
              pcPos.push(pos.getX(i), pos.getY(i), pos.getZ(i));
              pcCol.push(col ? col.getX(i) : 1, col ? col.getY(i) : 1, col ? col.getZ(i) : 1);
            }
          } catch { /* skip corrupted point geometry */ }
        }
      });
    } catch (err) {
      console.warn('ModelLoader: scene traversal failed, using empty geometry', err);
    }

    if (camPos.length > 0 && onCameraPositions) onCameraPositions(new Float32Array(camPos));

    let pts: THREE.Points | null = null;
    if (pcPos.length > 0) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pcPos), 3));
      geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pcCol), 3));
      const isGaussian = splatMode || viewMode === 'gaussian';
      const mat = new THREE.PointsMaterial({
        size: isGaussian ? pointSize * 4 : pointSize, vertexColors: true, sizeAttenuation: true,
        depthWrite: !isGaussian,
        blending: isGaussian ? THREE.AdditiveBlending : THREE.NormalBlending,
        transparent: true, opacity, clippingPlanes: clipPlanes || [], clipShadows: false,
        map: isGaussian ? splatTex : null, depthTest: true,
      });
      pts = new THREE.Points(geo, mat);
    }

    return { points: pts, meshes: meshList };
  }, [scene]);

  // Build mesh group when viewMode is mesh or wireframe
  const meshGroup = useMemo(() => {
    if (meshes.length === 0) return null;
    const group = new THREE.Group();
    meshes.forEach(m => {
      if (viewMode === 'wireframe') {
        const wGeo = new THREE.WireframeGeometry(m.geometry);
        const wLine = new THREE.LineSegments(wGeo, new THREE.LineBasicMaterial({ color: '#3b82f6', transparent: true, opacity: 0.6 }));
        group.add(wLine);
        return;
      }
      const clonedMat = (m.material as THREE.MeshStandardMaterial).clone();
      clonedMat.clipShadows = true;
      clonedMat.clippingPlanes = clipPlanes || [];
      const clonedMesh = new THREE.Mesh(m.geometry, clonedMat);
      group.add(clonedMesh);
    });
    return group;
  }, [meshes, viewMode, clipPlanes]);

  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).size = (splatMode || viewMode === 'gaussian') ? pointSize * 4 : pointSize; }, [pointSize, points, splatMode, viewMode]);
  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).opacity = opacity; }, [opacity, points]);
  useEffect(() => { if (points) (points.material as THREE.PointsMaterial).clippingPlanes = clipPlanes || []; }, [clipPlanes, points]);

  useEffect(() => {
    if (points && onPointsReady && (viewMode === 'points' || viewMode === 'gaussian')) {
      const pos = points.geometry.getAttribute('position');
      onPointsReady(points, pos ? pos.count : 0);
    }
  }, [points, onPointsReady, viewMode]);

  useEffect(() => {
    if (meshGroup && onMeshReady && (viewMode === 'mesh' || viewMode === 'wireframe')) {
      onMeshReady(meshGroup);
    }
  }, [meshGroup, onMeshReady, viewMode]);

  if (!points && !meshGroup) return null;

  const showMesh = (viewMode === 'mesh' || viewMode === 'wireframe') && meshGroup;
  const showPoints = (viewMode === 'points' || viewMode === 'gaussian');

  return (
    <>
      {showMesh && <primitive object={meshGroup} />}
      {showPoints && points && <primitive object={points} />}
    </>
  );
}
