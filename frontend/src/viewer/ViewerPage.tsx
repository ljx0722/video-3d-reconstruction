import { useState, useCallback, useRef, useEffect, Component } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import * as THREE from 'three';
import { cancelMeshRun, createMeshRun, deleteMeshRun, getJob, listMeshRuns, selectActiveMeshRun } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import ControlsPanel from './ControlsPanel';
import CrossSectionView from './CrossSectionView';
import { type BoxClip } from './Toolbar';
import { createPointColors } from './rendering';
import { useViewerRenderSettings } from './renderSettings';
import Sam2PromptPanel from './Sam2PromptPanel';
import type { Job, MeshRun, MeshRunPreset, Sam2Prompt } from '../types';

class ErrorBoundary extends Component<{ children: React.ReactNode }, { hasError: boolean; error: Error | null }> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="absolute inset-0 flex items-center justify-center bg-black">
          <div className="text-center">
            <div className="text-4xl mb-3 text-red-400">!</div>
            <p className="text-gray-400 text-sm">3D 视图加载失败</p>
            <p className="text-gray-600 text-xs mt-1">{this.state.error?.message}</p>
            <button onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-3 px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded">重试</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const statusSteps = [
  { label: '上传视频' }, { label: '等待处理' }, { label: 'GPU 推理计算中' },
  { label: '导出 3D 模型' }, { label: '重建完成' },
];
const defaultBoxClip: BoxClip = { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error: jobError, mutate: mutateJob } = useSWR<Job>(
    jobId ? `job-${jobId}` : null, () => getJob(jobId!),
    { refreshInterval: (data?: Job) => (data?.status === 'completed' || data?.status === 'partial' || data?.status === 'failed') ? 0 : 2000 });
  const { data: meshRuns = [], mutate: mutateMeshRuns } = useSWR<MeshRun[]>(
    jobId && job?.point_cloud_available ? `mesh-runs-${jobId}` : null,
    () => listMeshRuns(jobId!),
    { refreshInterval: (runs?: MeshRun[]) => runs?.some(run => run.status === 'queued' || run.status === 'processing') ? 2000 : 0 },
  );

  const { settings: renderSettings, updateSetting: updateRenderSetting, applyPreset: applyRenderPreset, reset: resetRenderSettings } = useViewerRenderSettings();
  const {
    pointSize,
    pointOpacity: opacity,
    showAxes,
    showTrajectory,
    orthographic,
    colorMode,
    exposure,
    showGrid,
    bloomStrength,
    edgeThreshold,
  } = renderSettings;
  const [viewMode, setViewMode] = useState<string>('points');
  const [fitToken, setFitToken] = useState(0);
  const [meshRunBusy, setMeshRunBusy] = useState(false);
  const [meshRunError, setMeshRunError] = useState<string | null>(null);
  const [sam2PromptOpen, setSam2PromptOpen] = useState(false);
  const setPointSize = useCallback((value: number) => updateRenderSetting('pointSize', value), [updateRenderSetting]);
  const setOpacity = useCallback((value: number) => updateRenderSetting('pointOpacity', value), [updateRenderSetting]);
  const setShowAxes = useCallback((value: boolean) => updateRenderSetting('showAxes', value), [updateRenderSetting]);
  const setShowTrajectory = useCallback((value: boolean) => updateRenderSetting('showTrajectory', value), [updateRenderSetting]);
  const setOrthographic = useCallback((value: boolean) => updateRenderSetting('orthographic', value), [updateRenderSetting]);
  const setColorMode = useCallback((value: string) => updateRenderSetting('colorMode', value), [updateRenderSetting]);
  const setExposure = useCallback((value: number) => updateRenderSetting('exposure', value), [updateRenderSetting]);
  const setShowGrid = useCallback((value: boolean) => updateRenderSetting('showGrid', value), [updateRenderSetting]);
  const setBloomStrength = useCallback((value: number) => updateRenderSetting('bloomStrength', value), [updateRenderSetting]);
  const setEdgeThreshold = useCallback((value: number) => updateRenderSetting('edgeThreshold', value), [updateRenderSetting]);

  // Processing
  const [pointCount, setPointCount] = useState(0);
  const [originalCount, setOriginalCount] = useState(0);

  // Clip
  const [boxClip, setBoxClip] = useState<BoxClip>(defaultBoxClip);
  const [orbitTarget, setOrbitTarget] = useState<[number, number, number]>([0, 0, 0]);

  // Measure
  const [measureMode, setMeasureMode] = useState(false);
  const measurePtsRef = useRef<THREE.Vector3[]>([]);
  const [distance, setDistance] = useState<number | null>(null);

  // Orient (3-point ground plane)
  const [orientMode, setOrientMode] = useState(false);
  const orientPtsRef = useRef<THREE.Vector3[]>([]);
  const [orientMarkers, setOrientMarkers] = useState<THREE.Vector3[] | null>(null);
  const [orientPlane, setOrientPlane] = useState<{ normal: THREE.Vector3; center: THREE.Vector3 } | null>(null);

  // Lasso
  const [lassoEnabled, setLassoEnabled] = useState(false);
  const lassoSelRef = useRef<Set<number>>(new Set());
  const [selectedCount, setSelectedCount] = useState(0);

  // History (undo/redo)
  const historyRef = useRef<{ pos: Float32Array; col: Float32Array }[]>([]);
  const historyIdx = useRef(-1);
  const pushHistory = useCallback(() => {
    const o = originalData.current;
    if (!o) return;
    const h = historyRef.current;
    h.length = historyIdx.current + 1;
    h.push({ pos: o.pos.slice(), col: o.col.slice() });
    if (h.length > 5) h.shift();
    else historyIdx.current = h.length - 1;
  }, []);

  // Annotations
  const [annotations, setAnnotations] = useState<{ id: number; p1: THREE.Vector3; p2: THREE.Vector3; label: string }[]>([]);
  const nextAnnoId = useRef(1);

  useEffect(() => {
    if (!jobId) {
      setMeshAvailable(false);
      return;
    }
    if (typeof job?.mesh_available === 'boolean') {
      setMeshAvailable(job.mesh_available);
      return;
    }
    if (job?.status !== 'completed' && job?.status !== 'partial') {
      setMeshAvailable(false);
      return;
    }
    fetch(`/files/${jobId}/result_mesh.glb`, { method: 'HEAD' })
      .then(r => setMeshAvailable(r.ok))
      .catch(() => setMeshAvailable(false));
  }, [jobId, job?.status, job?.mesh_available]);

  // Lasso selection listener
  useEffect(() => {
    const h = (e: Event) => {
      const detail = (e as CustomEvent).detail as { indices: Set<number> };
      lassoSelRef.current = detail.indices;
      setSelectedCount(detail.indices.size);
    };
    window.addEventListener('lasso-selection', h);
    return () => window.removeEventListener('lasso-selection', h);
  }, []);

  // Refs
  const pointsRef = useRef<THREE.Points | null>(null);
  const originalData = useRef<{ pos: Float32Array; col: Float32Array } | null>(null);
  const [editedPointData, setEditedPointData] = useState<{ pos: Float32Array; col: Float32Array } | null>(null);
  const [rawSectionData, setRawSectionData] = useState<{ pos: Float32Array; col: Float32Array } | null>(null);
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null);
  const [meshAvailable, setMeshAvailable] = useState(false);
  const sceneCamRef = useRef<THREE.Camera | null>(null);

  useEffect(() => {
    originalData.current = null;
    historyRef.current = [];
    historyIdx.current = -1;
    pointsRef.current = null;
    setEditedPointData(null);
    setRawSectionData(null);
    setPointCount(0);
    setOriginalCount(0);
    setOrbitTarget([0, 0, 0]);
  }, [jobId]);

  // Measure click
  useEffect(() => {
    if (!measureMode || !canvasEl || !pointsRef.current || !sceneCamRef.current) return;
    const h = (e: MouseEvent) => {
      if (e.button !== 0) return;
      if (!sceneCamRef.current || !pointsRef.current || !canvasEl) return;
      const r = canvasEl.getBoundingClientRect();
      const m = new THREE.Vector2(((e.clientX-r.left)/r.width)*2-1, -((e.clientY-r.top)/r.height)*2+1);
      const rc = new THREE.Raycaster();
      rc.params.Points!.threshold = 0.05;
      rc.setFromCamera(m, sceneCamRef.current);
      const hits = rc.intersectObject(pointsRef.current);
      if (hits.length > 0) {
        measurePtsRef.current.push(hits[0].point.clone());
        if (measurePtsRef.current.length >= 2) {
          const d = measurePtsRef.current[0].distanceTo(measurePtsRef.current[1]);
          setDistance(d);
          // Also create annotation
          const id = nextAnnoId.current++;
          setAnnotations(prev => [...prev, { id, p1: measurePtsRef.current[0].clone(), p2: measurePtsRef.current[1].clone(), label: `${(d*100).toFixed(1)}cm` }]);
          setMeasureMode(false);
          measurePtsRef.current = [];
        }
      }
    };
    canvasEl.addEventListener('click', h);
    return () => canvasEl.removeEventListener('click', h);
  }, [measureMode, canvasEl]);

  // Orient mode click — collect 3 ground plane points
  useEffect(() => {
    if (!orientMode || !canvasEl || !pointsRef.current || !sceneCamRef.current) return;
    const h = (e: MouseEvent) => {
      if (e.button !== 0) return;
      if (!sceneCamRef.current || !pointsRef.current || !canvasEl) return;
      const r = canvasEl.getBoundingClientRect();
      const m = new THREE.Vector2(((e.clientX-r.left)/r.width)*2-1, -((e.clientY-r.top)/r.height)*2+1);
      const rc = new THREE.Raycaster();
      rc.params.Points!.threshold = 0.05;
      rc.setFromCamera(m, sceneCamRef.current);
      const hits = rc.intersectObject(pointsRef.current);
      if (hits.length > 0) {
        const pt = hits[0].point.clone();
        const arr = [...orientPtsRef.current, pt];
        orientPtsRef.current = arr;
        setOrientMarkers(arr.slice());
        if (arr.length >= 3) {
          // Fit plane, compute rotation
          const c = new THREE.Vector3().addVectors(arr[0], arr[1]).add(arr[2]).multiplyScalar(1/3);
          // vectors in plane: v1 = p1-c, v2 = p2-c
          const v1 = new THREE.Vector3().subVectors(arr[0], c);
          const v2 = new THREE.Vector3().subVectors(arr[2], c);
          const n = new THREE.Vector3().crossVectors(v1, v2).normalize();
          // Ensure normal points roughly upward (toward Y+ if Y dominates, else keep)
          if (n.y < 0) n.negate();
          setOrientPlane({ normal: n.clone(), center: c.clone() });
          setOrientMode(false);
        }
      }
    };
    canvasEl.addEventListener('click', h);
    return () => canvasEl.removeEventListener('click', h);
  }, [orientMode, canvasEl]);

  const _updateGeometry = useCallback((newPos: Float32Array, newCol: Float32Array) => {
    const pointData = { pos: newPos, col: newCol };
    setEditedPointData(pointData);
    setRawSectionData(pointData);
    setPointCount(newPos.length / 3);
  }, []);

  const updateGeometry = useCallback((newPos: Float32Array, newCol: Float32Array) => {
    pushHistory();
    _updateGeometry(newPos, newCol);
  }, [pushHistory, _updateGeometry]);

  // Undo/Redo callbacks
  const undo = useCallback(() => {
    const h = historyRef.current;
    if (historyIdx.current <= 0 && h.length < 2) return;
    if (historyIdx.current > 0) {
      historyIdx.current--;
      const s = h[historyIdx.current];
      _updateGeometry(s.pos, s.col);
      originalData.current = s;
      setRawSectionData({ pos: s.pos, col: s.col });
      setOriginalCount(s.pos.length / 3);
    }
  }, [_updateGeometry]);

  const redo = useCallback(() => {
    const h = historyRef.current;
    if (historyIdx.current >= h.length - 1) return;
    historyIdx.current++;
    const s = h[historyIdx.current];
    _updateGeometry(s.pos, s.col);
    originalData.current = s;
    setRawSectionData({ pos: s.pos, col: s.col });
    setOriginalCount(s.pos.length / 3);
  }, [_updateGeometry]);

  // Ctrl+Z / Ctrl+Y undo-redo
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.key === 'z' || e.key === 'Z') { e.preventDefault(); undo(); }
      if (e.key === 'y' || e.key === 'Y' || (e.key === 'Z' && e.shiftKey)) { e.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [undo, redo]);

  // Delete key — remove selected lasso points
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      const sel = lassoSelRef.current;
      if (sel.size === 0 || !pointsRef.current) return;
      const pos = pointsRef.current.geometry.getAttribute('position');
      const col = pointsRef.current.geometry.getAttribute('color');
      const n = pos.count;
      const np = new Float32Array((n - sel.size) * 3);
      const nc = new Float32Array((n - sel.size) * 3);
      let j = 0;
      for (let i = 0; i < n; i++) {
        if (sel.has(i)) continue;
        np[j*3]=pos.getX(i); np[j*3+1]=pos.getY(i); np[j*3+2]=pos.getZ(i);
        nc[j*3]=col.getX(i); nc[j*3+1]=col.getY(i); nc[j*3+2]=col.getZ(i);
        j++;
      }
      updateGeometry(np, nc);
      originalData.current = { pos: np, col: nc };
      setRawSectionData({ pos: np, col: nc });
      setOriginalCount(np.length / 3);
      lassoSelRef.current.clear();
      setSelectedCount(0);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [updateGeometry]);

  const doApplyOrient = useCallback(() => {
    if (!orientPlane || !originalData.current) return;
    const n = orientPlane.normal;
    const up = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion().setFromUnitVectors(n, up);
    const pos = originalData.current.pos;
    const np = new Float32Array(pos.length);
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.length; i += 3) {
      v.set(pos[i], pos[i+1], pos[i+2]).applyQuaternion(q);
      np[i] = v.x; np[i+1] = v.y; np[i+2] = v.z;
    }
    const col = originalData.current.col;
    updateGeometry(np, col);
    originalData.current = { pos: np, col: col };
    setRawSectionData({ pos: np, col: col });
    let mx=Infinity,Mx=-Infinity,my=Infinity,My=-Infinity,mz=Infinity,Mz=-Infinity;
    for (let i=0;i<np.length;i+=3){
      mx=Math.min(mx,np[i]);Mx=Math.max(Mx,np[i]);
      my=Math.min(my,np[i+1]);My=Math.max(My,np[i+1]);
      mz=Math.min(mz,np[i+2]);Mz=Math.max(Mz,np[i+2]);
    }
    setOrbitTarget([(mx+Mx)/2,(my+My)/2,(mz+Mz)/2]);
    setOrientPlane(null);
    setOrientMarkers(null);
    orientPtsRef.current = [];
  }, [orientPlane, updateGeometry]);

  const doCancelOrient = useCallback(() => {
    setOrientMode(false);
    setOrientPlane(null);
    setOrientMarkers(null);
    orientPtsRef.current = [];
  }, []);

  const handlePointsReady = useCallback((mesh: THREE.Points) => {
    pointsRef.current = mesh;
    if (!originalData.current) {
      const pos = mesh.geometry.getAttribute('position');
      const col = mesh.geometry.getAttribute('color');
      if (pos) {
        const posCopy = (pos.array as Float32Array).slice();
        const colCopy = col ? (col.array as Float32Array).slice() : new Float32Array(pos.count * 3).fill(1);
        originalData.current = { pos: posCopy, col: colCopy };
        setEditedPointData({ pos: posCopy, col: colCopy });
        setRawSectionData({ pos: posCopy, col: colCopy });
        setOriginalCount(pos.count);
        setPointCount(pos.count);

        // Compute bounding box center for orbit target
        let mx = Infinity, Mx = -Infinity, my = Infinity, My = -Infinity, mz = Infinity, Mz = -Infinity;
        for (let i = 0; i < posCopy.length; i += 3) {
          if (posCopy[i] < mx) mx = posCopy[i]; if (posCopy[i] > Mx) Mx = posCopy[i];
          if (posCopy[i+1] < my) my = posCopy[i+1]; if (posCopy[i+1] > My) My = posCopy[i+1];
          if (posCopy[i+2] < mz) mz = posCopy[i+2]; if (posCopy[i+2] > Mz) Mz = posCopy[i+2];
        }
        setOrbitTarget([(mx+Mx)/2, (my+My)/2, (mz+Mz)/2]);
      }
    }
  }, []);

  const doVoxelDownsample = useCallback((voxelSize: number) => {
    if (!originalData.current) return;
    const pos = originalData.current.pos;
    const col = originalData.current.col;
    const voxel: Record<string, { ps: number[]; cs: number[]; n: number }> = {};
    for (let i = 0; i < pos.length; i += 3) {
      const k = `${Math.floor(pos[i]/voxelSize)},${Math.floor(pos[i+1]/voxelSize)},${Math.floor(pos[i+2]/voxelSize)}`;
      if (!voxel[k]) voxel[k] = { ps: [0,0,0], cs: [0,0,0], n: 0 };
      voxel[k].ps[0] += pos[i]; voxel[k].ps[1] += pos[i+1]; voxel[k].ps[2] += pos[i+2];
      voxel[k].cs[0] += col[i]; voxel[k].cs[1] += col[i+1]; voxel[k].cs[2] += col[i+2];
      voxel[k].n++;
    }
    const keys = Object.keys(voxel);
    const np = new Float32Array(keys.length * 3);
    const nc = new Float32Array(keys.length * 3);
    let j = 0;
    for (const v of Object.values(voxel)) {
      np[j]=v.ps[0]/v.n; np[j+1]=v.ps[1]/v.n; np[j+2]=v.ps[2]/v.n;
      nc[j]=v.cs[0]/v.n; nc[j+1]=v.cs[1]/v.n; nc[j+2]=v.cs[2]/v.n;
      j+=3;
    }
    updateGeometry(np, nc);
    originalData.current = { pos: np, col: nc };
    setOriginalCount(np.length / 3);
  }, [updateGeometry]);

  const doFastOutlier = useCallback((k: number, stdMul: number) => {
    const pos = pointsRef.current?.geometry.getAttribute('position');
    const col = pointsRef.current?.geometry.getAttribute('color');
    if (!pos) return;
    const n = pos.count;
    if (n < 10) return;

    // Random-neighbor statistical filtering (fast, O(n*k) with k constant)
    const dists = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let sum = 0;
      for (let j = 0; j < k; j++) {
        const ri = Math.floor(Math.random() * n);
        if (ri === i) continue;
        const dx = pos.getX(i) - pos.getX(ri);
        const dy = pos.getY(i) - pos.getY(ri);
        const dz = pos.getZ(i) - pos.getZ(ri);
        sum += Math.sqrt(dx*dx + dy*dy + dz*dz);
      }
      dists[i] = sum / k;
    }
    const mean = dists.reduce((a,b)=>a+b)/n;
    const std = Math.sqrt(dists.reduce((a,b)=>a+(b-mean)*(b-mean),0)/n);
    const th = mean + stdMul * std;

    const keep: number[] = [];
    for (let i = 0; i < n; i++) {
      if (dists[i] < th) keep.push(i);
    }
    if (keep.length < 3) return;

    const np = new Float32Array(keep.length * 3);
    const nc = new Float32Array(keep.length * 3);
    for (let i = 0; i < keep.length; i++) {
      const idx = keep[i];
      np[i*3]=pos.getX(idx); np[i*3+1]=pos.getY(idx); np[i*3+2]=pos.getZ(idx);
      nc[i*3]=col?.getX(idx)||1; nc[i*3+1]=col?.getY(idx)||1; nc[i*3+2]=col?.getZ(idx)||1;
    }
    updateGeometry(np, nc);
    originalData.current = { pos: np, col: nc };
    setOriginalCount(np.length / 3);
  }, [updateGeometry]);

  const doReset = useCallback(() => {
    if (!originalData.current) return;
    updateGeometry(originalData.current.pos, originalData.current.col);
    measurePtsRef.current = [];
    setDistance(null);
    setBoxClip(defaultBoxClip);
  }, [updateGeometry]);

  const doExport = useCallback((format: string) => {
    const pos = pointsRef.current?.geometry.getAttribute('position');
    const col = pointsRef.current?.geometry.getAttribute('color');
    if (!pos) return;
    const n = pos.count;

    if (format === 'GLB') {
      window.open(`/files/${jobId}/result.glb`, '_blank');
      return;
    }

    let content = '';
    if (format === 'PLY') {
      content = `ply\nformat ascii 1.0\nelement vertex ${n}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n`;
      const linearToByte = (value: number) => {
        const linear = Math.max(0, Math.min(1, value));
        const srgb = linear <= 0.0031308 ? linear * 12.92 : 1.055 * Math.pow(linear, 1 / 2.4) - 0.055;
        return Math.round(srgb * 255);
      };
      for (let i = 0; i < n; i++) {
        const r = col ? linearToByte(col.getX(i)) : 255;
        const g = col ? linearToByte(col.getY(i)) : 255;
        const b = col ? linearToByte(col.getZ(i)) : 255;
        content += `${pos.getX(i).toFixed(6)} ${pos.getY(i).toFixed(6)} ${pos.getZ(i).toFixed(6)} ${r} ${g} ${b}\n`;
      }
    } else if (format === 'XYZ') {
      for (let i = 0; i < n; i++) content += `${pos.getX(i).toFixed(6)} ${pos.getY(i).toFixed(6)} ${pos.getZ(i).toFixed(6)}\n`;
    } else if (format === 'LAS') {
      content = `# LAS export not yet supported. Use PLY instead.\n`;
    }

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `pointcloud.${format.toLowerCase()}`; a.click();
    URL.revokeObjectURL(url);
  }, [jobId]);

  const doScreenshot = useCallback(() => {
    const c = document.querySelector('canvas');
    if (!c) return;
    const a = document.createElement('a');
    a.download = `screenshot-${Date.now()}.png`;
    a.href = c.toDataURL('image/png');
    a.click();
  }, []);

  const doResetView = useCallback(() => {
    setOrthographic(false);
    setFitToken(token => token + 1);
  }, []);

  const applyColor = useCallback((mode: string) => {
    const source = originalData.current;
    if (!source) return;
    const colors = createPointColors(mode, source.pos, source.col);
    setEditedPointData({ pos: source.pos, col: colors });
    setRawSectionData({ pos: source.pos, col: colors });
  }, []);

  useEffect(() => {
    if (pointsRef.current && originalData.current) applyColor(colorMode);
  }, [colorMode, applyColor]);

  const activeMeshRun = meshRuns.find(run => run.is_active && run.status === 'completed') ?? null;
  const activeMeshUrl = activeMeshRun?.output_url ?? job?.mesh_url ?? null;
  const resolvedMeshAvailable = Boolean(activeMeshUrl || meshAvailable);

  const withMeshRunMutation = useCallback(async (operation: () => Promise<unknown>) => {
    setMeshRunBusy(true);
    setMeshRunError(null);
    try {
      await operation();
      await Promise.all([mutateMeshRuns(), mutateJob()]);
    } catch (error) {
      setMeshRunError(error instanceof Error ? error.message : '表面重建操作失败');
    } finally {
      setMeshRunBusy(false);
    }
  }, [mutateJob, mutateMeshRuns]);

  const handleCreateMeshRun = useCallback((preset: MeshRunPreset) => {
    if (!jobId) return;
    void withMeshRunMutation(() => createMeshRun(jobId, preset));
  }, [jobId, withMeshRunMutation]);

  const handleCreateHighQuality = useCallback((prompts: Sam2Prompt[]) => {
    if (!jobId) return;
    setSam2PromptOpen(false);
    void withMeshRunMutation(() => createMeshRun(jobId, 'high-quality', {
      use_sam2: true,
      sam2_prompts: prompts,
    }));
  }, [jobId, withMeshRunMutation]);

  const handleSelectMeshRun = useCallback((runId: string | null) => {
    if (!jobId) return;
    void withMeshRunMutation(() => selectActiveMeshRun(jobId, runId));
  }, [jobId, withMeshRunMutation]);

  const handleCancelMeshRun = useCallback((runId: string) => {
    if (!jobId) return;
    void withMeshRunMutation(() => cancelMeshRun(jobId, runId));
  }, [jobId, withMeshRunMutation]);

  const handleDeleteMeshRun = useCallback((runId: string) => {
    if (!jobId) return;
    void withMeshRunMutation(() => deleteMeshRun(jobId, runId));
  }, [jobId, withMeshRunMutation]);

  const isProcessing = job?.status === 'uploaded' || job?.status === 'processing';
  const canViewPointCloud = job?.status === 'completed' || job?.status === 'partial' || job?.point_cloud_available === true;
  const progressPct = Math.max(2, Math.min(100, (job?.progress || 0) * 100));
  const currentStep = job?.status === 'completed' ? 4 : job?.status === 'partial' ? 3 : isProcessing ? (job?.progress||0)>=0.15?2:1 : 0;
  const detailText = ((job as any)?.detail || (job as any)?.settings?._detail || '');

  if (jobError) return <p className="text-center text-red-400 mt-12">加载作业失败</p>;
  if (!job) return <div className="flex items-center justify-center h-full"><div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div className="h-[calc(100vh-2.5rem)] flex">
      {/* Left Panel */}
      <div className="w-64 flex-shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-gray-800 flex-shrink-0">
          <div className="text-xs text-gray-500 mb-2">原始视频</div>
          <div className="w-full aspect-video bg-black rounded overflow-hidden">
            <video src={`/api/v1/jobs/${jobId}/video`} controls className="w-full h-full object-contain" preload="metadata" />
          </div>
        </div>
        <div className="p-3 flex-1 overflow-auto">
          <div className="text-xs text-gray-500 mb-3">处理进度</div>
          {isProcessing && (
            <div className="mb-4 flex items-center gap-3">
              <div className="relative w-12 h-12">
                <svg className="w-12 h-12 -rotate-90" viewBox="0 0 48 48">
                  <circle cx="24" cy="24" r="20" fill="none" stroke="#1f2937" strokeWidth="3" />
                  <circle cx="24" cy="24" r="20" fill="none" stroke="url(#pg)" strokeWidth="3" strokeLinecap="round"
                    strokeDasharray={`${1.25*progressPct} 126`} />
                  <defs><linearGradient id="pg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#3B82F6" /><stop offset="100%" stopColor="#8B5CF6" /></linearGradient></defs>
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">{Math.round(progressPct)}%</span>
              </div>
              <div>
                <div className="text-sm font-medium">处理中...</div>
                <div className="text-xs text-gray-500">{job.num_frames?`${job.num_frames} 帧`:'准备中'}</div>
                {detailText && <div className="text-[10px] text-blue-400/70 mt-0.5">{detailText}</div>}
              </div>
            </div>
          )}
          {job.status==='completed'&&<div className="mb-4 text-sm text-green-400">&#x2713; 处理完成</div>}
          {job.status==='partial'&&<div className="mb-4 p-2 bg-amber-500/10 border border-amber-500/20 rounded text-xs text-amber-300">点云已生成，Mesh 不可用：{job.mesh_error || job.error_message || (job as any).detail || '未知错误'}</div>}
          {job.status==='failed'&&<div className="mb-4 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">处理失败: {job.error_message || (job as any).detail || '未知错误'}</div>}
          <div className="space-y-1">
            {statusSteps.map((step,i)=>(
              <div key={i} className={`flex items-center gap-2 py-1 px-2 rounded text-xs ${i===currentStep?'bg-blue-500/10 text-blue-400':i<currentStep?'text-green-400/70':'text-gray-600'}`}>
                <span className="w-4 text-center">{i<currentStep?'✓':i===currentStep?'●':'○'}</span><span>{step.label}</span>
              </div>
            ))}
          </div>
          {(job.status==='completed'||job.status==='partial')&&(
            <div className="mt-4 pt-3 border-t border-gray-800 text-xs text-gray-500 space-y-1">
              {job.num_frames&&<p>总帧数：{job.num_frames}</p>}
              {job.num_points&&<p>点云数量：{(job.num_points/10000).toFixed(1)} 万</p>}
              {job.processing_time_secs&&<p>处理耗时：{job.processing_time_secs.toFixed(1)} 秒</p>}
            </div>
          )}
        </div>
        <div className="p-3 border-t border-gray-800 flex gap-2">
          <Link to="/" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300">上传新视频</Link>
          <Link to="/jobs" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300">作业历史</Link>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 relative bg-black">
        <div className="absolute inset-0" ref={el=>{if(el){const c=el.querySelector('canvas');if(c&&c!==canvasEl)setCanvasEl(c as HTMLCanvasElement);}}} />
        {canViewPointCloud?(
          <>
            <ErrorBoundary>
            <ViewerCanvas jobId={job.id} pointUrl={job.result_url ?? undefined} meshUrl={activeMeshUrl} pointSize={pointSize} opacity={opacity}
              onPointsReady={handlePointsReady} boxClip={boxClip}
              showAxes={showAxes} orthographic={orthographic}
              showGrid={showGrid} showTrajectory={showTrajectory}
              bloomStrength={bloomStrength}
              bloomThreshold={renderSettings.bloomThreshold}
              bloomSmoothing={renderSettings.bloomSmoothing}
              exposure={exposure}
              backgroundColor={renderSettings.backgroundColor}
              fov={renderSettings.fov}
              lightIntensity={renderSettings.lightIntensity}
              ambientLight={renderSettings.ambientLight}
              keyLight={renderSettings.keyLight}
              fillLight={renderSettings.fillLight}
              rimLight={renderSettings.rimLight}
              edgeThreshold={edgeThreshold}
              edgeColor={renderSettings.edgeColor}
              edgeOpacity={renderSettings.edgeOpacity}
              gaussianRadius={renderSettings.gaussianRadius}
              gaussianOpacity={renderSettings.gaussianOpacity}
              gaussianFalloff={renderSettings.gaussianFalloff}
              gaussianEdgeCutoff={renderSettings.gaussianEdgeCutoff}
              gaussianBlend={renderSettings.gaussianBlend}
              gaussianDepthWrite={renderSettings.gaussianDepthWrite}
              pointShape={renderSettings.pointShape}
              pointDepthTest={renderSettings.pointDepthTest}
              surfaceRoughness={renderSettings.surfaceRoughness}
              surfaceMetalness={renderSettings.surfaceMetalness}
              surfaceColorBrightness={renderSettings.surfaceColorBrightness}
              surfaceFlatShading={renderSettings.surfaceFlatShading}
              surfaceDoubleSide={renderSettings.surfaceDoubleSide}
              fitToken={fitToken}
              colorsAreLinear={job.artifact_metadata?.color_space === 'linear-srgb'}
              editedPointData={editedPointData}
              orbitTarget={orbitTarget}
              viewMode={viewMode as any}
              meshAvailable={resolvedMeshAvailable}
              orientMarkers={orientMarkers}
              orientPlane={orientPlane}
              onUpdateClip={setBoxClip}
              lassoEnabled={lassoEnabled}
              annotations={annotations}
              onCameraRef={(cam) => { sceneCamRef.current = cam; }}
            />
            </ErrorBoundary>
            <KeyboardHint />
            <CrossSectionView positions={rawSectionData?.pos ?? null} colors={rawSectionData?.col ?? null} />
            <DisplayModeBar viewMode={viewMode} setViewMode={setViewMode} meshAvailable={resolvedMeshAvailable} meshError={job.mesh_error} />
            <MeshRunPanel
              runs={meshRuns}
              legacyMeshAvailable={Boolean(job.mesh_available && !activeMeshRun)}
              meshSourceAvailable={Boolean(job.mesh_source_available)}
              highQualityAvailable={Boolean(job.mesh_source_available && job.video_metadata)}
              busy={meshRunBusy}
              error={meshRunError}
              onCreate={handleCreateMeshRun}
              onCreateHighQuality={() => setSam2PromptOpen(true)}
              onSelect={handleSelectMeshRun}
              onCancel={handleCancelMeshRun}
              onDelete={handleDeleteMeshRun}
            />
            {sam2PromptOpen && job.video_metadata && (
              <Sam2PromptPanel
                videoUrl={`/api/v1/jobs/${job.id}/video`}
                metadata={job.video_metadata}
                onCancel={() => setSam2PromptOpen(false)}
                onSubmit={handleCreateHighQuality}
              />
            )}
            <ControlsPanel
              pointSize={pointSize} setPointSize={setPointSize}
              opacity={opacity} setOpacity={setOpacity}
              pointCount={pointCount} originalCount={originalCount}
              orthographic={orthographic} setOrthographic={setOrthographic}
              onVoxelDownsample={doVoxelDownsample}
              onFastOutlierRemove={doFastOutlier}
              onReset={doReset}
              boxClip={boxClip} setBoxClip={setBoxClip}
              measureMode={measureMode} setMeasureMode={setMeasureMode}
              distance={distance} clearMeasure={()=>{measurePtsRef.current=[];setDistance(null);}}
              onExport={doExport}
              showAxes={showAxes} setShowAxes={setShowAxes}
              colorMode={colorMode} setColorMode={setColorMode}
              exposure={exposure} setExposure={setExposure}
              viewMode={viewMode} edgeThreshold={edgeThreshold} setEdgeThreshold={setEdgeThreshold}
              onScreenshot={doScreenshot} onResetView={doResetView}
              showGrid={showGrid} setShowGrid={setShowGrid}
              bloomStrength={bloomStrength} setBloomStrength={setBloomStrength}
              showTrajectory={showTrajectory} setShowTrajectory={setShowTrajectory}
              orientMode={orientMode} setOrientMode={setOrientMode}
              orientMarkers={orientMarkers}
              orientPlane={orientPlane}
              onApplyOrient={doApplyOrient}
              onCancelOrient={doCancelOrient}
              lassoEnabled={lassoEnabled} setLassoEnabled={setLassoEnabled}
              selectedCount={selectedCount}
              annotations={annotations} onClearAnnotations={() => setAnnotations([])}
              renderSettings={renderSettings}
              updateRenderSetting={updateRenderSetting}
              applyRenderPreset={applyRenderPreset}
              resetRenderSettings={resetRenderSettings}
            />
          </>
        ):isProcessing?(
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">正在重建三维模型...</p>
              <p className="text-gray-600 text-xs mt-1">{Math.round(progressPct)}%</p>
            </div>
          </div>
        ):job.status==='failed'?(
          <div className="absolute inset-0 flex items-center justify-center text-gray-500"><div className="text-center"><div className="text-4xl mb-3">!</div><p>处理失败</p></div></div>
        ):(
          <div className="absolute inset-0 flex items-center justify-center"><div className="text-center"><div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /><p className="text-gray-400 text-sm">正在重建三维模型...</p></div></div>
        )}
      </div>
    </div>
  );
}

function MeshRunPanel({ runs, legacyMeshAvailable, meshSourceAvailable, highQualityAvailable, busy, error, onCreate, onCreateHighQuality, onSelect, onCancel, onDelete }: {
  runs: MeshRun[];
  legacyMeshAvailable: boolean;
  meshSourceAvailable: boolean;
  highQualityAvailable: boolean;
  busy: boolean;
  error: string | null;
  onCreate: (preset: MeshRunPreset) => void;
  onCreateHighQuality: () => void;
  onSelect: (runId: string | null) => void;
  onCancel: (runId: string) => void;
  onDelete: (runId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const presetLabels: Record<MeshRunPreset, string> = {
    quick: '快速预览',
    detail: '细节表面',
    'open-boundary': '开放边界',
    balanced: '均衡 TSDF',
    'high-quality': '高质量 · SAM2',
  };
  const statusLabels: Record<MeshRun['status'], string> = {
    queued: '等待中', processing: '生成中', completed: '已完成', failed: '失败', cancelled: '已取消',
  };

  return (
    <div className="absolute left-3 bottom-3 z-10">
      <button onClick={() => setOpen(value => !value)}
        className="rounded-lg border border-gray-800 bg-gray-900/90 px-3 py-1.5 text-[11px] text-gray-300 backdrop-blur hover:bg-gray-800">
        重新生成表面{runs.some(run => run.status === 'queued' || run.status === 'processing') ? ' · 进行中' : ''}
      </button>
      {open && (
        <div className="mt-2 w-80 max-h-[65vh] overflow-y-auto rounded-xl border border-gray-800 bg-gray-950/95 p-3 text-[11px] shadow-2xl backdrop-blur">
          <div className="mb-2 font-semibold text-gray-200">表面重建版本</div>
          <p className="mb-3 text-[10px] leading-4 text-gray-500">创建新版本需要 GPU 计算，不会覆盖原始点云或旧表面。</p>
          <div className="grid grid-cols-2 gap-1 mb-2">
            {([
              ['quick', '快速', '约 20 秒–2 分钟'],
              ['balanced', '均衡（推荐）', 'CUDA TSDF，约 2–8 分钟'],
              ['detail', '细节', '更高面数与细节'],
              ['open-boundary', '开放边界', '适合局部扫描'],
            ] as [MeshRunPreset, string, string][]).map(([preset, label, title]) => {
              const disabled = busy || (preset === 'balanced' && !meshSourceAvailable);
              return (
              <button key={preset} title={preset === 'balanced' && !meshSourceAvailable ? '仅含 mesh-source-v1 的新任务可用' : title} disabled={disabled}
                onClick={() => onCreate(preset)}
                className="rounded border border-blue-500/20 bg-blue-500/10 px-1 py-1.5 text-[10px] text-blue-300 hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-30">
                {label}
              </button>
              );
            })}
          </div>
          {!meshSourceAvailable && <p className="mb-3 text-[9px] text-gray-600">均衡 TSDF 仅新任务可用；历史作业缺少深度、置信度和相机参数。</p>}
          <button onClick={onCreateHighQuality} disabled={busy || !highQualityAvailable}
            title={!highQualityAvailable ? '高质量需要新任务的深度、置信度与相机元数据' : '用 SAM2 标记保留/排除区域后进行 TSDF 重建'}
            className="mb-2 w-full rounded border border-purple-500/30 bg-purple-500/10 px-2 py-1.5 text-left text-[10px] text-purple-300 hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-30">
            高质量 · SAM2 区域标记重建
          </button>
          {error && <div className="mb-2 rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-300">{error}</div>}
          {legacyMeshAvailable && (
            <button onClick={() => onSelect(null)} disabled={busy}
              className="mb-2 w-full rounded bg-gray-800/60 px-2 py-1.5 text-left text-[10px] text-gray-400 hover:text-white">
              当前原始表面 · 旧版兼容结果
            </button>
          )}
          <div className="space-y-2">
            {runs.map(run => (
              <div key={run.id} className={`rounded-lg border p-2 ${run.is_active ? 'border-blue-500/40 bg-blue-500/10' : 'border-gray-800 bg-gray-900/60'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-gray-300">{presetLabels[run.preset]}</span>
                  <span className={`text-[9px] ${run.status === 'failed' ? 'text-red-400' : run.status === 'completed' ? 'text-green-400' : 'text-amber-400'}`}>
                    {statusLabels[run.status]}{run.is_active ? ' · 当前' : ''}
                  </span>
                </div>
                {(run.status === 'queued' || run.status === 'processing') && (
                  <div className="mt-1.5">
                    <div className="h-1 overflow-hidden rounded bg-gray-800"><div className="h-full bg-blue-500" style={{ width: `${Math.max(2, run.progress * 100)}%` }} /></div>
                    <div className="mt-1 flex justify-between text-[9px] text-gray-600"><span>{run.detail}</span><span>{Math.round(run.progress * 100)}%</span></div>
                  </div>
                )}
                {run.error_message && <div className="mt-1 text-[9px] text-red-400/80">{run.error_message}</div>}
                {run.status === 'completed' && (
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-[9px] text-gray-500">
                    {typeof run.stats?.entity_qualified === 'boolean' && (
                      <span className={`rounded px-1 ${run.stats.entity_qualified ? 'bg-green-500/15 text-green-300' : 'bg-gray-700/40 text-gray-400'}`}>
                        {run.stats.entity_qualified ? '实体' : '表面'}
                      </span>
                    )}
                    {run.stats?.mesh_triangles ? <span>{run.stats.mesh_triangles.toLocaleString()} 面</span> : null}
                    {typeof run.stats?.boundary_edges === 'number' && run.stats.boundary_edges > 0 ? <span>{run.stats.boundary_edges} 边界边</span> : null}
                    {typeof run.stats?.watertight === 'boolean' && <span>{run.stats.watertight ? '水密' : '非水密'}</span>}
                    {typeof run.stats?.coverage === 'number' ? <span>覆盖 {(run.stats.coverage * 100).toFixed(0)}%</span> : null}
                  </div>
                )}
                <div className="mt-2 flex gap-1">
                  {run.status === 'completed' && !run.is_active && (
                    <button onClick={() => onSelect(run.id)} disabled={busy}
                      className="rounded bg-blue-500/15 px-2 py-1 text-[9px] text-blue-300">查看此版本</button>
                  )}
                  {(run.status === 'queued' || run.status === 'processing') && (
                    <button onClick={() => onCancel(run.id)} disabled={busy || run.cancel_requested}
                      className="rounded bg-amber-500/10 px-2 py-1 text-[9px] text-amber-300">{run.cancel_requested ? '取消中' : '取消'}</button>
                  )}
                  {(run.status === 'failed' || run.status === 'cancelled') && (
                    <button onClick={() => onDelete(run.id)} disabled={busy}
                      className="rounded bg-red-500/10 px-2 py-1 text-[9px] text-red-300">删除记录</button>
                  )}
                </div>
              </div>
            ))}
            {!runs.length && <div className="py-3 text-center text-[10px] text-gray-600">暂无独立表面版本</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function KeyboardHint() {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const t = setTimeout(() => setVisible(false), 12000);
    const h = (e: KeyboardEvent) => { if (['w','a','s','d','q','e','ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(e.key)) setVisible(false); };
    window.addEventListener('keydown', h, { once: true });
    return () => { clearTimeout(t); window.removeEventListener('keydown', h); };
  }, []);
  if (!visible) return null;
  return (
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
      <div className="bg-gray-900/85 backdrop-blur rounded-lg px-4 py-2.5 text-[10px] text-gray-400 border border-gray-700 flex gap-4 transition-opacity duration-500" style={{ opacity: visible ? 1 : 0 }}>
        <span><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono">W</kbd><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono ml-0.5">S</kbd> 前后</span>
        <span><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono">A</kbd><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono ml-0.5">D</kbd> 左右</span>
        <span><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono">Space</kbd> 上升 · <kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono">Shift</kbd> 下降</span>
        <span><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono">Q</kbd><kbd className="px-1 py-0.5 rounded bg-gray-800 text-gray-300 text-[9px] font-mono ml-0.5">E</kbd> 旋转</span>
      </div>
    </div>
  );
}

function DisplayModeBar({ viewMode, setViewMode, meshAvailable, meshError }: { viewMode: string; setViewMode: (v: string) => void; meshAvailable: boolean; meshError?: string | null }) {
  const modes = [
    ['points', '点云', '标准点云显示'],
    ['gaussian', '高斯溅射', '基于点云的高斯软点显示；当前工件不含协方差参数'],
    ['mesh', '表面', '着色三角表面'],
    ['wireframe', '结构线', '仅显示边界与明显折痕'],
  ] as const;

  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-1.5">
      <div className="bg-gray-900/95 backdrop-blur rounded-full px-1 py-1 flex gap-0.5 border border-gray-800 shadow-xl">
        {modes.map(([k, label, title]) => (
          <button key={k} onClick={() => setViewMode(k)} title={title}
            disabled={(k === 'mesh' || k === 'wireframe') && !meshAvailable}
            className={`px-4 py-1 rounded-full text-[11px] font-medium transition-all duration-200
              ${viewMode === k
                ? 'bg-blue-500 text-white shadow-md shadow-blue-500/30'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/70'}
              ${(k === 'mesh' || k === 'wireframe') && !meshAvailable ? 'opacity-25 cursor-not-allowed hover:text-gray-500 hover:bg-transparent' : ''}`}>
            {label}
          </button>
        ))}
      </div>
      {!meshAvailable && meshError && (
        <div className="max-w-sm rounded border border-amber-500/30 bg-gray-950/95 px-3 py-1 text-center text-[10px] text-amber-300 shadow-lg">
          Mesh 不可用：{meshError}
        </div>
      )}
    </div>
  );
}
