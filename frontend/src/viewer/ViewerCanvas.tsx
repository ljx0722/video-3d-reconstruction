import { Suspense, useState, useCallback, useRef, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { TrackballControls, GizmoHelper, GizmoViewport, Grid, Html, Line, OrthographicCamera, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import { getResultUrl, getMeshUrl } from '../api/client';
import ModelLoader from './ModelLoader';
import EDLEffect from './EDLEffect';
import type { BoxClip } from './Toolbar';

interface Props {
  jobId: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points, count?: number) => void;
  onMeshReady?: (mesh: THREE.Group) => void;
  boxClip?: BoxClip;
  showAxes?: boolean;
  orthographic?: boolean;
  splatMode?: boolean;
  showGrid?: boolean;
  showTrajectory?: boolean;
  edlStrength?: number;
  orbitTarget?: [number, number, number];
  viewMode?: 'points' | 'gaussian' | 'mesh' | 'wireframe';
  meshAvailable?: boolean;
  orientMarkers?: THREE.Vector3[] | null;
  orientPlane?: { normal: THREE.Vector3; center: THREE.Vector3 } | null;
  onUpdateClip?: (clip: BoxClip) => void;
}

function ClipBox({ boxClip, onUpdate }: { boxClip: BoxClip; onUpdate?: (c: BoxClip) => void }) {
  if (!boxClip.enabled) return null;
  const { camera, size, gl } = useThree();
  const dragRef = useRef<{ idx: number; sign: 1 | -1; initVal: number; initMouse: number } | null>(null);
  const handleRefs = useRef<THREE.Mesh[]>([]);
  const [mx, my, mz] = boxClip.min; const [Mx, My, Mz] = boxClip.max;
  const ctr: [number, number, number] = [(mx + Mx) / 2, (my + My) / 2, (mz + Mz) / 2];
  const sz: [number, number, number] = [Mx - mx, My - my, Mz - mz];
  const hScale = Math.max(sz[0], sz[1], sz[2], 0.1) * 0.04;

  const handles = [
    { idx: 0, sign:  1 as const, pos: [Mx, ctr[1], ctr[2]] as [number, number, number], col: '#ef4444' },
    { idx: 0, sign: -1 as const, pos: [mx, ctr[1], ctr[2]] as [number, number, number], col: '#ef4444' },
    { idx: 1, sign:  1 as const, pos: [ctr[0], My, ctr[2]] as [number, number, number], col: '#22c55e' },
    { idx: 1, sign: -1 as const, pos: [ctr[0], my, ctr[2]] as [number, number, number], col: '#22c55e' },
    { idx: 2, sign:  1 as const, pos: [ctr[0], ctr[1], Mz] as [number, number, number], col: '#3b82f6' },
    { idx: 2, sign: -1 as const, pos: [ctr[0], ctr[1], mz] as [number, number, number], col: '#3b82f6' },
  ];

  useEffect(() => {
    const el = gl.domElement;
    const rc = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    const onDown = (e: PointerEvent) => {
      mouse.x = (e.offsetX / size.width) * 2 - 1;
      mouse.y = -(e.offsetY / size.height) * 2 + 1;
      rc.setFromCamera(mouse, camera);
      const targets = handleRefs.current.filter(Boolean);
      const hits = rc.intersectObjects(targets, false);
      if (hits.length > 0) {
        const i = targets.indexOf(hits[0].object as THREE.Mesh);
        if (i >= 0) {
          const h = handles[i];
          const key = h.sign > 0 ? 'max' : 'min';
          dragRef.current = {
            idx: h.idx, sign: h.sign,
            initVal: boxClip[key][h.idx],
            initMouse: h.idx === 0 ? mouse.x : h.idx === 1 ? -mouse.y : mouse.y
          };
          e.stopPropagation();
        }
      }
    };
    const onMove = (e: PointerEvent) => {
      if (!dragRef.current) return;
      const dr = dragRef.current;
      mouse.x = (e.offsetX / size.width) * 2 - 1;
      mouse.y = -(e.offsetY / size.height) * 2 + 1;
      // Ray through handle's current plane (plane at handle world coords, not origin)
      const axisVec = new THREE.Vector3(); axisVec.setComponent(dr.idx, 1);
      rc.setFromCamera(mouse, camera);
      const pt = new THREE.Vector3();
      // Project onto a plane at the handle's current world coordinate
      const currentVal = boxClip[dr.sign > 0 ? 'max' : 'min'][dr.idx];
      const perpPlane = new THREE.Plane(axisVec, -currentVal);
      if (!rc.ray.intersectPlane(perpPlane, pt) || !onUpdate) return;
      const val = pt.getComponent(dr.idx);
      const key = dr.sign > 0 ? 'max' : 'min';
      const other = dr.sign > 0 ? 'min' : 'max';
      const arr = [...boxClip[key]] as [number, number, number];
      arr[dr.idx] = Number(val.toFixed(4));
      // Clamp
      if (dr.sign > 0) arr[dr.idx] = Math.max(arr[dr.idx], boxClip[other][dr.idx] + 0.0005);
      else arr[dr.idx] = Math.min(arr[dr.idx], boxClip[other][dr.idx] - 0.0005);
      onUpdate({ ...boxClip, [key]: arr });
    };
    const onUp = () => { dragRef.current = null; };

    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [camera, size, boxClip, onUpdate, gl, handles]);

  const geom = new THREE.BoxGeometry(sz[0], sz[1], sz[2]);
  geom.translate(ctr[0], ctr[1], ctr[2]);

  return (
    <group>
      <lineSegments>
        <edgesGeometry args={[geom]} />
        <lineBasicMaterial color="#22c55e" transparent opacity={0.7} depthTest={true} />
      </lineSegments>
      {handles.map((h, i) => (
        <mesh key={i} ref={el => { if (el) handleRefs.current[i] = el; }} position={h.pos}>
          <boxGeometry args={[hScale, hScale, hScale]} />
          <meshBasicMaterial color={h.col} />
        </mesh>
      ))}
    </group>
  );
}

function CameraTrail({ positions }: { positions: Float32Array }) {
  const n = positions.length / 3;
  if (n < 2) return null;

  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < n; i++) {
    pts.push(new THREE.Vector3(positions[i*3], positions[i*3+1], positions[i*3+2]));
  }

  const sorted: THREE.Vector3[] = [pts[0]];
  const remaining = new Set(pts.slice(1).map((_, i) => i + 1));
  while (remaining.size > 0) {
    const last = sorted[sorted.length - 1];
    let bestIdx = -1;
    let bestDist = Infinity;
    for (const idx of remaining) {
      const d = last.distanceToSquared(pts[idx]);
      if (d < bestDist) { bestDist = d; bestIdx = idx; }
    }
    sorted.push(pts[bestIdx]);
    remaining.delete(bestIdx);
  }

  const linePoints = sorted.map(p => [p.x, p.y, p.z] as [number, number, number]);

  const colors = sorted.map((_, i) => {
    const t = i / Math.max(1, sorted.length - 1);
    return [t, 0.2 + (1 - Math.abs(t - 0.5) * 2) * 0.4, 1 - t] as [number, number, number];
  });

  const center = sorted[Math.floor(sorted.length / 2)];

  return (
    <group>
      <Line points={linePoints} color="white" lineWidth={1.5} vertexColors={colors} />
      <Html position={[center.x, center.y + 0.3, center.z]} center>
        <div className="bg-gray-900/80 backdrop-blur px-2 py-0.5 rounded text-[10px] text-gray-400 whitespace-nowrap border border-gray-700 select-none">
          摄像机轨迹 · {n} 帧
        </div>
      </Html>
      <mesh position={sorted[0].toArray()}>
        <sphereGeometry args={[0.025, 8, 8]} />
        <meshBasicMaterial color="#3B82F6" />
      </mesh>
      <mesh position={sorted[sorted.length - 1].toArray()}>
        <sphereGeometry args={[0.025, 8, 8]} />
        <meshBasicMaterial color="#EF4444" />
      </mesh>
    </group>
  );
}

function AdaptiveControls({ target }: { target: [number, number, number] }) {
  const ref = useRef<any>(null);

  useFrame(({ camera }) => {
    if (ref.current) {
      const d = camera.position.length();
      ref.current.rotateSpeed = Math.max(0.8, Math.min(6, d * 0.7));
      ref.current.zoomSpeed = Math.max(0.15, Math.min(2.5, d * 0.12));
      ref.current.panSpeed = Math.max(0.15, Math.min(3, d * 0.25));
    }
  });

  return (
    <TrackballControls
      ref={ref}
      target={target}
    />
  );
}

function OrientMarkers({ markers, plane }: { markers: THREE.Vector3[] | null; plane: { normal: THREE.Vector3; center: THREE.Vector3 } | null }) {
  if (!markers || markers.length === 0) return null;
  const colors = ['#3B82F6', '#F59E0B', '#EF4444'];
  // Compute plane size from bounding box of markers
  let maxDist = 1;
  if (markers.length >= 3) {
    const c = new THREE.Vector3();
    markers.forEach(p => c.add(p));
    c.multiplyScalar(1/markers.length);
    markers.forEach(p => maxDist = Math.max(maxDist, c.distanceTo(p)));
  }
  const planeSize = maxDist * 1.5;
  return (
    <group>
      {markers.map((pt, i) => (
        <group key={i}>
          <mesh position={pt.toArray()}>
            <sphereGeometry args={[0.04, 16, 16]} />
            <meshBasicMaterial color={colors[i]} />
          </mesh>
          <Html position={[pt.x, pt.y + 0.1, pt.z]} center>
            <div className="bg-gray-900/90 text-white text-[10px] px-1.5 py-0.5 rounded font-mono border border-gray-600 select-none">
              {i+1}
            </div>
          </Html>
        </group>
      ))}
      {plane && (
        <mesh position={plane.center.toArray()} quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1), plane.normal)}>
          <planeGeometry args={[planeSize, planeSize]} />
          <meshBasicMaterial color="#22c55e" side={THREE.DoubleSide} transparent opacity={0.25} depthTest={true} />
        </mesh>
      )}
    </group>
  );
}

function KeyboardFly() {
  const keys = useRef<Record<string, boolean>>({});

  useEffect(() => {
    const onDown = (e: KeyboardEvent) => { keys.current[e.key] = true; };
    const onUp   = (e: KeyboardEvent) => { keys.current[e.key] = false; };
    window.addEventListener('keydown', onDown);
    window.addEventListener('keyup', onUp);
    return () => { window.removeEventListener('keydown', onDown); window.removeEventListener('keyup', onUp); };
  }, []);

  useFrame(({ camera }) => {
    const k = keys.current;
    // Skip if any modifier held (e.g. user typing in a text field)
    if (k['Control'] || k['Alt'] || k['Meta']) return;

    // Camera world-space basis
    const target = new THREE.Vector3(0, 0, 0); // TrackballControls always targets origin
    const forward = new THREE.Vector3().subVectors(target, camera.position).normalize();
    const worldUp = new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(forward, worldUp).normalize();
    const up = new THREE.Vector3().crossVectors(right, forward).normalize();

    const dist = camera.position.length();
    // Base speed: 0.5% of distance per frame at 60fps (≈ 30% of distance per second)
    const moveSpeed = Math.max(0.04, dist * 0.005);
    // Rotation speed: ~2 degrees per keypress at 60fps
    const rotSpeed = 0.03;

    const delta = new THREE.Vector3();

    // WASD / Arrow keys: move camera in world-local space
    if (k['w'] || k['W'] || k['ArrowUp'])    delta.add(forward.clone().multiplyScalar( moveSpeed));
    if (k['s'] || k['S'] || k['ArrowDown'])  delta.add(forward.clone().multiplyScalar(-moveSpeed));
    if (k['a'] || k['A'] || k['ArrowLeft'])  delta.add(right.clone().multiplyScalar(-moveSpeed));
    if (k['d'] || k['D'] || k['ArrowRight']) delta.add(right.clone().multiplyScalar( moveSpeed));

    // Space / Shift: vertical movement along camera's local up
    if (k[' ']) delta.add(up.clone().multiplyScalar(moveSpeed));
    if (k['Shift']) delta.add(up.clone().multiplyScalar(-moveSpeed));

    camera.position.add(delta);

    // Q / E: yaw left/right around the target
    if (k['q'] || k['Q']) {
      const q = new THREE.Quaternion().setFromAxisAngle(worldUp, rotSpeed);
      camera.position.sub(target).applyQuaternion(q).add(target);
    }
    if (k['e'] || k['E']) {
      const q = new THREE.Quaternion().setFromAxisAngle(worldUp, -rotSpeed);
      camera.position.sub(target).applyQuaternion(q).add(target);
    }
  });

  return null;
}

function AxesHelper3D() {
  return (
    <group>
      <mesh position={[1.5, 0, 0]}><boxGeometry args={[3, 0.02, 0.02]} /><meshBasicMaterial color="#ef4444" /></mesh>
      <mesh position={[0, 1.5, 0]}><boxGeometry args={[0.02, 3, 0.02]} /><meshBasicMaterial color="#22c55e" /></mesh>
      <mesh position={[0, 0, 1.5]}><boxGeometry args={[0.02, 0.02, 3]} /><meshBasicMaterial color="#3b82f6" /></mesh>
    </group>
  );
}

export default function ViewerCanvas({
  jobId, pointSize, opacity = 1, onPointsReady, onMeshReady,
  boxClip, showAxes, orthographic, splatMode, showGrid, showTrajectory = true,
  edlStrength = 0.4, orbitTarget = [0, 0, 0], viewMode = 'points', meshAvailable = false,
  orientMarkers = null, orientPlane = null, onUpdateClip,
}: Props) {
  const [camPositions, setCamPositions] = useState<Float32Array | null>(null);
  const defaultBox: BoxClip = boxClip || { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };
  const activeBox = boxClip || defaultBox;

  const handleCameras = useCallback((pos: Float32Array) => setCamPositions(pos), []);

  const threeClipPlanes: THREE.Plane[] = [];
  if (activeBox.enabled) {
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 1,0,0), -activeBox.min[0]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3(-1,0,0),  activeBox.max[0]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,1,0), -activeBox.min[1]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,-1,0), activeBox.max[1]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,0,1), -activeBox.min[2]));
    threeClipPlanes.push(new THREE.Plane(new THREE.Vector3( 0,0,-1),activeBox.max[2]));
  }

  return (
    <Canvas
      className="!absolute inset-0"
      gl={{ preserveDrawingBuffer: true, antialias: true, localClippingEnabled: true }}
      frameloop="always"
      style={{ background: '#0a0a0f' }}
    >
      <PerspectiveCamera makeDefault={!orthographic} position={[2, 1, 3]} fov={50} near={0.01} far={200} />
      <OrthographicCamera makeDefault={orthographic} position={[2, 1, 3]} zoom={80} near={0.01} far={200} />

      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={null}>
        <ModelLoader
          url={(viewMode === 'mesh' || viewMode === 'wireframe') && meshAvailable ? getMeshUrl(jobId) : getResultUrl(jobId)}
          pointSize={pointSize}
          opacity={opacity}
          onPointsReady={onPointsReady as any}
          onMeshReady={onMeshReady as any}
          onCameraPositions={handleCameras}
          clipPlanes={threeClipPlanes}
          splatMode={splatMode}
          viewMode={viewMode}
        />
      </Suspense>

      {camPositions && showTrajectory && <CameraTrail positions={camPositions} />}

      <ClipBox boxClip={activeBox} onUpdate={onUpdateClip} />

      {showGrid && <Grid infiniteGrid fadeDistance={50} fadeStrength={5} sectionSize={1} cellSize={0.5} sectionColor="#374151" cellColor="#1f2937" />}

      {showAxes && <AxesHelper3D />}

      <GizmoHelper alignment="top-right" margin={[60, 60]}>
        <GizmoViewport axisColors={['#ef4444', '#22c55e', '#3b82f6']} labelColor="#9ca3af" />
      </GizmoHelper>

      <AdaptiveControls target={orbitTarget} />

      <KeyboardFly />

      <OrientMarkers markers={orientMarkers} plane={orientPlane} />

      <EDLEffect edlStrength={edlStrength} />
    </Canvas>
  );
}
