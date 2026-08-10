import { Suspense, useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { TrackballControls, GizmoHelper, GizmoViewcube, Grid, Html, Line, OrthographicCamera, PerspectiveCamera } from '@react-three/drei';
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
  lassoEnabled?: boolean;
  annotations?: { id: number; p1: THREE.Vector3; p2: THREE.Vector3; label: string }[];
  onCameraRef?: (cam: THREE.Camera) => void;
}

function LassoOverlay({ enabled }: { enabled: boolean }) {
  const { camera, size, gl, scene } = useThree();
  const [poly, setPoly] = useState<THREE.Vector2[]>([]);
  const selRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!enabled) return;
    const el = gl.domElement;
    const rect = () => el.getBoundingClientRect();

    const onClick = (e: MouseEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault(); e.stopPropagation();
      const r = rect();
      poly.push(new THREE.Vector2(e.clientX - r.left, e.clientY - r.top));
      setPoly([...poly]);
    };
    const onDbl = () => {
      if (poly.length < 3) return;
      let foundPts: any = null;
      scene.traverse((c: any) => { if (c.isPoints) foundPts = c; });
      if (!foundPts) return;
      const pos = foundPts.geometry.getAttribute('position');
      const selected = new Set<number>();
      const p3 = new THREE.Vector3();
      const p2 = new THREE.Vector2();
      for (let i = 0; i < pos.count; i++) {
        p3.set(pos.getX(i), pos.getY(i), pos.getZ(i));
        p3.project(camera);
        p2.set((p3.x + 1) / 2 * size.width, (-p3.y + 1) / 2 * size.height);
        if (pointInPolygon(p2, poly)) selected.add(i);
      }
      selRef.current = selected;
      window.dispatchEvent(new CustomEvent('lasso-selection', { detail: { indices: selected } }));
      setPoly([]);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setPoly([]); selRef.current.clear(); window.dispatchEvent(new CustomEvent('lasso-selection', { detail: { indices: new Set<number>() } })); }
    };

    el.addEventListener('click', onClick);
    el.addEventListener('dblclick', onDbl);
    window.addEventListener('keydown', onKeyDown);
    return () => { el.removeEventListener('click', onClick); el.removeEventListener('dblclick', onDbl); window.removeEventListener('keydown', onKeyDown); };
  }, [enabled, poly, camera, size, gl, scene]);

  if (!enabled || poly.length === 0) return null;
  const pts = poly.map(v => [v.x, v.y]);
  // SVG overlay for lasso polygon
  return (
    <Html fullscreen>
      <svg className="absolute inset-0 pointer-events-none" style={{ width: '100%', height: '100%' }}>
        <polygon points={pts.map(p => p.join(',')).join(' ')} fill="rgba(59,130,246,0.15)" stroke="#3B82F6" strokeWidth="1.5" strokeDasharray="4 2" />
        {poly.map((v, i) => (
          <circle key={i} cx={v.x} cy={v.y} r="3" fill="#3B82F6" />
        ))}
      </svg>
    </Html>
  );
}

function pointInPolygon(p: THREE.Vector2, poly: THREE.Vector2[]): boolean {
  let inside = false;
  const n = poly.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = poly[i].x, yi = poly[i].y;
    const xj = poly[j].x, yj = poly[j].y;
    if ((yi > p.y) !== (yj > p.y) && p.x < ((xj - xi) * (p.y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

function AnnotationLabels({ annotations }: { annotations: { id: number; p1: THREE.Vector3; p2: THREE.Vector3; label: string }[] }) {
  if (!annotations || annotations.length === 0) return null;
  return (
    <group>
      {annotations.map(a => {
        const mid = new THREE.Vector3().addVectors(a.p1, a.p2).multiplyScalar(0.5);
        const dist = a.p1.distanceTo(a.p2);
        return (
          <group key={a.id}>
            <Line points={[a.p1.toArray(), a.p2.toArray()] as [number,number,number][]} color="#F59E0B" lineWidth={1.5} />
            <mesh position={a.p1.toArray()}><sphereGeometry args={[0.015, 8, 8]} /><meshBasicMaterial color="#F59E0B" /></mesh>
            <mesh position={a.p2.toArray()}><sphereGeometry args={[0.015, 8, 8]} /><meshBasicMaterial color="#F59E0B" /></mesh>
            <Html position={mid.toArray()} center>
              <div className="bg-gray-900/90 backdrop-blur px-2 py-0.5 rounded text-[10px] text-yellow-400 whitespace-nowrap border border-yellow-600/50 select-none">
                {a.label || `${(dist * 100).toFixed(1)}cm`}
              </div>
            </Html>
          </group>
        );
      })}
    </group>
  );
}

function ClipBox({ boxClip, onUpdate }: { boxClip: BoxClip; onUpdate?: (c: BoxClip) => void }) {
  if (!boxClip.enabled) return null;
  const { camera, size, gl } = useThree();
  const boxClipRef = useRef(boxClip);
  boxClipRef.current = boxClip;
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;
  const dragRef = useRef<{ idx: number; sign: 1 | -1 } | null>(null);
  const hitRefs = useRef<THREE.Mesh[]>([]);
  const visRefs = useRef<THREE.Mesh[]>([]);
  const [mx, my, mz] = boxClip.min; const [Mx, My, Mz] = boxClip.max;
  const ctr: [number, number, number] = [(mx + Mx) / 2, (my + My) / 2, (mz + Mz) / 2];
  const sz: [number, number, number] = [Mx - mx, My - my, Mz - mz];
  const diag = Math.max(0.1, Mx - mx, My - my, Mz - mz);
  const hScale = diag * 0.06;
  const hitScale = diag * 0.12;

  const handles = [
    { idx: 0, sign:  1 as const, pos: [Mx, ctr[1], ctr[2]] as [number, number, number], col: '#ef4444' },
    { idx: 0, sign: -1 as const, pos: [mx, ctr[1], ctr[2]] as [number, number, number], col: '#ef4444' },
    { idx: 1, sign:  1 as const, pos: [ctr[0], My, ctr[2]] as [number, number, number], col: '#22c55e' },
    { idx: 1, sign: -1 as const, pos: [ctr[0], my, ctr[2]] as [number, number, number], col: '#22c55e' },
    { idx: 2, sign:  1 as const, pos: [ctr[0], ctr[1], Mz] as [number, number, number], col: '#3b82f6' },
    { idx: 2, sign: -1 as const, pos: [ctr[0], ctr[1], mz] as [number, number, number], col: '#3b82f6' },
  ];

  // One-time effect for pointer events (stable refs, no boxClip dep)
  useEffect(() => {
    const el = gl.domElement;
    const rc = new THREE.Raycaster();
    // Increase threshold so rays that pass near (not through) the hitbox still count
    rc.params.Points = undefined as any;
    const mouse = new THREE.Vector2();

    const onDown = (e: PointerEvent) => {
      mouse.x = (e.offsetX / size.width) * 2 - 1;
      mouse.y = -(e.offsetY / size.height) * 2 + 1;
      rc.setFromCamera(mouse, camera);
      // Only check the invisible large hitboxes (much easier to grab)
      const targets = hitRefs.current.filter(Boolean);
      if (targets.length === 0) return;
      const hits = rc.intersectObjects(targets, false);
      if (hits.length > 0) {
        const i = targets.indexOf(hits[0].object as THREE.Mesh);
        if (i >= 0 && i < handles.length) {
          e.stopPropagation();
          e.preventDefault();
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          dragRef.current = { idx: handles[i].idx, sign: handles[i].sign };
        }
      }
    };
    const onMove = (e: PointerEvent) => {
      if (!dragRef.current) return;
      const dr = dragRef.current;
      const box = boxClipRef.current;
      const upd = onUpdateRef.current;
      if (!upd) return;
      mouse.x = (e.offsetX / size.width) * 2 - 1;
      mouse.y = -(e.offsetY / size.height) * 2 + 1;
      const axisVec = new THREE.Vector3(); axisVec.setComponent(dr.idx, 1);
      rc.setFromCamera(mouse, camera);
      const currentVal = box[dr.sign > 0 ? 'max' : 'min'][dr.idx];
      const perpPlane = new THREE.Plane(axisVec, -currentVal);
      const pt = new THREE.Vector3();
      if (!rc.ray.intersectPlane(perpPlane, pt)) return;
      const val = pt.getComponent(dr.idx);
      const key = dr.sign > 0 ? 'max' : 'min';
      const other = dr.sign > 0 ? 'min' : 'max';
      const arr = [...box[key]] as [number, number, number];
      arr[dr.idx] = Number(val.toFixed(4));
      if (dr.sign > 0) arr[dr.idx] = Math.max(arr[dr.idx], box[other][dr.idx] + 0.0005);
      else arr[dr.idx] = Math.min(arr[dr.idx], box[other][dr.idx] - 0.0005);
      upd({ ...box, [key]: arr });
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
  }, [camera, size, gl]); // no boxClip dep — uses refs

  const geom = useMemo(() => {
    const g = new THREE.BoxGeometry(sz[0], sz[1], sz[2]);
    g.translate(ctr[0], ctr[1], ctr[2]);
    return g;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sz[0], sz[1], sz[2], ctr[0], ctr[1], ctr[2]]);

  return (
    <group>
      <lineSegments>
        <edgesGeometry args={[geom]} />
        <lineBasicMaterial color="#22c55e" transparent opacity={0.7} depthTest={true} />
      </lineSegments>
      {handles.map((h, i) => (
        <group key={i}>
          {/* Large invisible hitbox — actual click target */}
          <mesh ref={el => { if (el) hitRefs.current[i] = el; }} position={h.pos} visible={false}>
            <sphereGeometry args={[hitScale, 8, 8]} />
            <meshBasicMaterial visible={false} />
          </mesh>
          {/* Visual handle */}
          <mesh ref={el => { if (el) visRefs.current[i] = el; }} position={h.pos}>
            <sphereGeometry args={[hScale, 12, 12]} />
            <meshStandardMaterial color={h.col} emissive={h.col} emissiveIntensity={0.5} roughness={0.2} />
          </mesh>
        </group>
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

  useFrame(({ camera, invalidate }) => {
    if (ref.current) {
      const d = camera.position.length();
      ref.current.rotateSpeed = Math.max(0.8, Math.min(6, d * 0.7));
      ref.current.zoomSpeed = Math.max(0.15, Math.min(2.5, d * 0.12));
      ref.current.panSpeed = Math.max(0.15, Math.min(3, d * 0.25));
    }
    invalidate(); // demand loop trigger
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
    if (k['Control'] || k['Alt'] || k['Meta']) return;

    const target = new THREE.Vector3(0, 0, 0);
    const forward = new THREE.Vector3().subVectors(target, camera.position).normalize();
    const worldUp = new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(forward, worldUp).normalize();
    const up = new THREE.Vector3().crossVectors(right, forward).normalize();

    const dist = camera.position.length();
    const moveSpeed = Math.max(0.04, dist * 0.005);
    const rotSpeed = 0.03;

    const delta = new THREE.Vector3();

    if (k['w'] || k['W'] || k['ArrowUp'])    delta.add(forward.clone().multiplyScalar( moveSpeed));
    if (k['s'] || k['S'] || k['ArrowDown'])  delta.add(forward.clone().multiplyScalar(-moveSpeed));
    if (k['a'] || k['A'] || k['ArrowLeft'])  delta.add(right.clone().multiplyScalar(-moveSpeed));
    if (k['d'] || k['D'] || k['ArrowRight']) delta.add(right.clone().multiplyScalar( moveSpeed));
    if (k[' ']) delta.add(up.clone().multiplyScalar(moveSpeed));
    if (k['Shift']) delta.add(up.clone().multiplyScalar(-moveSpeed));

    camera.position.add(delta);

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

function ViewPresetHandler({ onUpdateClip, activeBox }: { onUpdateClip?: (c: BoxClip) => void; activeBox: BoxClip }) {
  const { camera } = useThree();

  useEffect(() => {
    const h = (e: Event) => {
      const { pos } = (e as CustomEvent).detail as { pos: [number,number,number] };
      const dist = camera.position.length();
      const dir = new THREE.Vector3(pos[0], pos[1], pos[2]).normalize();
      camera.position.copy(dir.multiplyScalar(dist));
      camera.lookAt(0, 0, 0);
    };
    window.addEventListener('view-preset', h);
    return () => window.removeEventListener('view-preset', h);
  }, [camera]);

  useEffect(() => {
    const h = (e: Event) => {
      const { axis, sign } = (e as CustomEvent).detail as { axis: string; sign: number };
      if (!onUpdateClip) return;
      const c = { ...activeBox, enabled: true };
      const i = axis === 'x' ? 0 : axis === 'y' ? 1 : 2;
      const mid = (c.min[i] + c.max[i]) / 2;
      const key = sign > 0 ? 'max' : 'min';
      const arr = [...c[key]] as [number,number,number];
      arr[i] = mid;
      c[key] = arr;
      onUpdateClip(c);
    };
    window.addEventListener('clip-preset', h);
    return () => window.removeEventListener('clip-preset', h);
  }, [onUpdateClip, activeBox]);

  return null;
}

function LoadingFallback() {
  return (
    <Html center>
      <div className="flex items-center gap-2 text-gray-400 text-xs select-none pointer-events-none">
        <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        加载模型...
      </div>
    </Html>
  );
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
  lassoEnabled = false, annotations = [], onCameraRef,
}: Props) {
  const [camPositions, setCamPositions] = useState<Float32Array | null>(null);
  const defaultBox: BoxClip = boxClip || { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };
  const activeBox = boxClip || defaultBox;

  const handleCameras = useCallback((pos: Float32Array) => setCamPositions(pos), []);

  // Capture camera ref for ViewerPage raycasting
  const camHolderRef = useRef<THREE.Camera | null>(null);
  useFrame(({ camera }) => {
    if (camHolderRef.current !== camera) {
      camHolderRef.current = camera;
      onCameraRef?.(camera);
    }
  });

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
      gl={{ preserveDrawingBuffer: true, antialias: false, localClippingEnabled: true }}
      frameloop="always"
      style={{ background: '#0a0a0f' }}
    >
      <PerspectiveCamera makeDefault={!orthographic} position={[2, 1, 3]} fov={50} near={0.01} far={200} />
      <OrthographicCamera makeDefault={orthographic} position={[2, 1, 3]} zoom={80} near={0.01} far={200} />

      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />

      <Suspense fallback={<LoadingFallback />}>
        <ModelLoader
          url={(viewMode === 'mesh' || viewMode === 'wireframe') && meshAvailable ? getMeshUrl(jobId) : getResultUrl(jobId)}
          pointSize={pointSize}
          opacity={opacity}
          onPointsReady={onPointsReady as any}
          onMeshReady={onMeshReady as any}
          onCameraPositions={handleCameras}
          clipPlanes={threeClipPlanes}
          splatMode={splatMode || viewMode === 'gaussian'}
          viewMode={viewMode}
        />
      </Suspense>

      {camPositions && showTrajectory && <CameraTrail positions={camPositions} />}

      <ClipBox boxClip={activeBox} onUpdate={onUpdateClip} />

      {showGrid && <Grid infiniteGrid fadeDistance={50} fadeStrength={5} sectionSize={1} cellSize={0.5} sectionColor="#374151" cellColor="#1f2937" />}

      {showAxes && <AxesHelper3D />}

      <GizmoHelper alignment="top-right" margin={[80, 80]}>
        <GizmoViewcube faces={['右', '左', '上', '下', '前', '后']} color="#1e293b" hoverColor="#3b82f6" textColor="#ffffff" strokeColor="#64748b" />
      </GizmoHelper>

      <ViewPresetHandler onUpdateClip={onUpdateClip} activeBox={activeBox} />

      <AdaptiveControls target={orbitTarget} />

      <KeyboardFly />

      <OrientMarkers markers={orientMarkers} plane={orientPlane} />

      <LassoOverlay enabled={lassoEnabled} />

      <AnnotationLabels annotations={annotations} />

      <EDLEffect edlStrength={edlStrength} />
    </Canvas>
  );
}
