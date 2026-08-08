import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import * as THREE from 'three';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import Toolbar, { type ClipPlane, type BoxClip } from './Toolbar';
import type { Job } from '../types';

const POINT_SIZE = 0.008;
const statusSteps = [
  { label: '上传视频' }, { label: '等待处理' }, { label: 'GPU 推理计算中' },
  { label: '导出 3D 模型' }, { label: '重建完成' },
];

const defaultClipPlanes: ClipPlane[] = [
  { axis: 'x', offset: -1.5, enabled: false, negative: false },
  { axis: 'x', offset: 1.5, enabled: false, negative: true },
  { axis: 'y', offset: -1, enabled: false, negative: false },
  { axis: 'y', offset: 1, enabled: false, negative: true },
  { axis: 'z', offset: -1, enabled: false, negative: false },
  { axis: 'z', offset: 1, enabled: false, negative: true },
];

const defaultBoxClip: BoxClip = { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error: jobError } = useSWR<Job>(
    jobId ? `job-${jobId}` : null, () => getJob(jobId!), { refreshInterval: 2000 });

  // Visualization
  const [pointSize, setPointSize] = useState(POINT_SIZE);
  const [opacity, setOpacity] = useState(1);
  const [showAxes, setShowAxes] = useState(false);
  const [bgColor, setBgColor] = useState<'dark' | 'light'>('dark');

  // Processing
  const [pointCount, setPointCount] = useState(0);
  const [originalCount, setOriginalCount] = useState(0);

  // Clip
  const [clipPlanes, setClipPlanes] = useState<ClipPlane[]>(defaultClipPlanes);
  const [boxClip, setBoxClip] = useState<BoxClip>(defaultBoxClip);

  // Measure
  const [measureMode, setMeasureMode] = useState(false);
  const measurePtsRef = useRef<THREE.Vector3[]>([]);
  const [distance, setDistance] = useState<number | null>(null);

  // Refs
  const pointsRef = useRef<THREE.Points | null>(null);
  const originalData = useRef<{ pos: Float32Array; col: Float32Array } | null>(null);
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null);

  // Measure click handler
  useEffect(() => {
    if (!measureMode || !canvasEl || !pointsRef.current) return;
    const handle = (e: MouseEvent) => {
      if (e.button !== 0) return;
      const rect = canvasEl.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const raycaster = new THREE.Raycaster();
      raycaster.params.Points.threshold = 0.05;
      raycaster.setFromCamera(mouse, new THREE.PerspectiveCamera(50, rect.width / rect.height, 0.1, 100));
      const hits = raycaster.intersectObject(pointsRef.current!);
      if (hits.length > 0) {
        const pt = hits[0].point.clone();
        measurePtsRef.current = [...measurePtsRef.current, pt];
        if (measurePtsRef.current.length >= 2) {
          setDistance(measurePtsRef.current[0].distanceTo(measurePtsRef.current[1]));
          setMeasureMode(false);
          measurePtsRef.current = [];
        }
      }
    };
    canvasEl.addEventListener('click', handle);
    return () => canvasEl.removeEventListener('click', handle);
  }, [measureMode, canvasEl]);

  const updateGeometry = useCallback((newPos: Float32Array, newCol: Float32Array) => {
    if (!pointsRef.current) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(newPos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(newCol, 3));
    pointsRef.current.geometry = geo;
    setPointCount(newPos.length / 3);
  }, []);

  const handlePointsReady = useCallback((mesh: THREE.Points) => {
    pointsRef.current = mesh;
    if (!originalData.current) {
      const pos = mesh.geometry.getAttribute('position');
      const col = mesh.geometry.getAttribute('color');
      if (pos) {
        originalData.current = {
          pos: (pos.array as Float32Array).slice(),
          col: col ? (col.array as Float32Array).slice() : new Float32Array(pos.count * 3),
        };
        setOriginalCount(pos.count);
        setPointCount(pos.count);
      }
    }
  }, []);

  const doVoxelDownsample = useCallback((voxelSize: number) => {
    if (!originalData.current) return;
    const pos = originalData.current.pos;
    const col = originalData.current.col;
    const voxel: Record<string, { ps: number[]; cs: number[]; n: number }> = {};
    for (let i = 0; i < pos.length; i += 3) {
      const vx = Math.floor(pos[i] / voxelSize);
      const vy = Math.floor(pos[i + 1] / voxelSize);
      const vz = Math.floor(pos[i + 2] / voxelSize);
      const key = `${vx},${vy},${vz}`;
      if (!voxel[key]) voxel[key] = { ps: [0, 0, 0], cs: [0, 0, 0], n: 0 };
      voxel[key].ps[0] += pos[i]; voxel[key].ps[1] += pos[i + 1]; voxel[key].ps[2] += pos[i + 2];
      voxel[key].cs[0] += col[i]; voxel[key].cs[1] += col[i + 1]; voxel[key].cs[2] += col[i + 2];
      voxel[key].n++;
    }
    const keys = Object.keys(voxel);
    const np = new Float32Array(keys.length * 3);
    const nc = new Float32Array(keys.length * 3);
    let j = 0;
    for (const v of Object.values(voxel)) {
      np[j] = v.ps[0] / v.n; np[j + 1] = v.ps[1] / v.n; np[j + 2] = v.ps[2] / v.n;
      nc[j] = v.cs[0] / v.n; nc[j + 1] = v.cs[1] / v.n; nc[j + 2] = v.cs[2] / v.n;
      j += 3;
    }
    updateGeometry(np, nc);
  }, [updateGeometry]);

  const doOutlierRemove = useCallback((k: number, stdMul: number) => {
    if (!originalData.current) return;
    const pos = pointsRef.current?.geometry.getAttribute('position');
    const col = pointsRef.current?.geometry.getAttribute('color');
    if (!pos) return;
    const n = pos.count;
    // Build KD-tree by computing distances to k-nearest neighbors (simplified: use full pairwise for small sets, random sample for large)
    const sampleSize = Math.min(n, 5000);
    const step = Math.max(1, Math.floor(n / sampleSize));
    const distances: number[] = [];

    // Compute mean distance for each sample point to its k nearest
    for (let i = 0; i < n; i += step) {
      let distSum = 0;
      let count = 0;
      for (let j = 0; j < n && count < k * 3; j++) {
        if (i === j) continue;
        const dx = pos.getX(i) - pos.getX(j);
        const dy = pos.getY(i) - pos.getY(j);
        const dz = pos.getZ(i) - pos.getZ(j);
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        distSum += d; count++;
      }
      distances.push(distSum / Math.max(1, count));
    }

    const mean = distances.reduce((a,b)=>a+b,0)/distances.length;
    const std = Math.sqrt(distances.reduce((a,b)=>a+(b-mean)*(b-mean),0)/distances.length);
    const threshold = mean + stdMul * std;

    // Filter all points
    const keep: number[] = [];
    for (let i = 0; i < n; i += step) {
      let distSum = 0; let count = 0;
      for (let j = 0; j < n && count < k * 3; j++) {
        if (i === j) continue;
        const dx = pos.getX(i) - pos.getX(j);
        const dy = pos.getY(i) - pos.getY(j);
        const dz = pos.getZ(i) - pos.getZ(j);
        distSum += Math.sqrt(dx*dx+dy*dy+dz*dz); count++;
      }
      if (distSum / Math.max(1, count) < threshold) keep.push(i);
    }

    if (keep.length === 0) return;
    const np = new Float32Array(keep.length * 3);
    const nc = new Float32Array(keep.length * 3);
    for (let i = 0; i < keep.length; i++) {
      const idx = keep[i];
      np[i*3]=pos.getX(idx); np[i*3+1]=pos.getY(idx); np[i*3+2]=pos.getZ(idx);
      if (col) { nc[i*3]=col.getX(idx); nc[i*3+1]=col.getY(idx); nc[i*3+2]=col.getZ(idx); }
    }
    updateGeometry(np, nc);
  }, [updateGeometry]);

  const doReset = useCallback(() => {
    if (!originalData.current) return;
    updateGeometry(originalData.current.pos, originalData.current.col);
    measurePtsRef.current = [];
    setDistance(null);
    setClipPlanes(defaultClipPlanes);
    setBoxClip(defaultBoxClip);
  }, [updateGeometry]);

  const doExport = useCallback((format: string) => {
    const pos = pointsRef.current?.geometry.getAttribute('position');
    const col = pointsRef.current?.geometry.getAttribute('color');
    if (!pos) return;

    let content = '';
    const n = pos.count;

    if (format === 'PLY') {
      content = `ply\nformat ascii 1.0\nelement vertex ${n}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n`;
      for (let i = 0; i < n; i++) {
        const r = col ? Math.round(Math.min(1, col.getX(i)) * 255) : 255;
        const g = col ? Math.round(Math.min(1, col.getY(i)) * 255) : 255;
        const b = col ? Math.round(Math.min(1, col.getZ(i)) * 255) : 255;
        content += `${pos.getX(i).toFixed(6)} ${pos.getY(i).toFixed(6)} ${pos.getZ(i).toFixed(6)} ${r} ${g} ${b}\n`;
      }
    } else if (format === 'XYZ') {
      for (let i = 0; i < n; i++) {
        content += `${pos.getX(i).toFixed(6)} ${pos.getY(i).toFixed(6)} ${pos.getZ(i).toFixed(6)}\n`;
      }
    } else if (format === 'GLB') {
      // GLB already downloadable via /files/{id}/result.glb
      window.open(`/files/${jobId}/result.glb`, '_blank');
      return;
    }

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pointcloud.${format.toLowerCase()}`;
    a.click();
    URL.revokeObjectURL(url);
  }, [jobId]);

  const isProcessing = job?.status === 'uploaded' || job?.status === 'processing';
  const progressPct = Math.max(2, Math.min(100, (job?.progress || 0) * 100));
  const currentStep = job?.status === 'completed' ? 4 : isProcessing ? (job?.progress || 0) >= 0.15 ? 2 : 1 : 0;

  if (jobError) return <p className="text-center text-red-400 mt-12">加载作业失败</p>;
  if (!job) return <div className="flex items-center justify-center h-full"><div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div className="h-[calc(100vh-2.5rem)] flex">
      {/* Left Panel */}
      <div className="w-64 flex-shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-gray-800">
          <div className="text-xs text-gray-500 mb-2">原始视频</div>
          <video src={`/api/v1/gpu/video/${jobId}`} controls className="w-full rounded bg-black" preload="metadata" />
        </div>
        <div className="p-3 flex-1 overflow-auto">
          <div className="text-xs text-gray-500 mb-3">处理进度</div>
          {isProcessing && (
            <div className="mb-4 flex items-center gap-3">
              <div className="relative w-12 h-12">
                <svg className="w-12 h-12 -rotate-90" viewBox="0 0 48 48">
                  <circle cx="24" cy="24" r="20" fill="none" stroke="#1f2937" strokeWidth="3" />
                  <circle cx="24" cy="24" r="20" fill="none" stroke="url(#pg)" strokeWidth="3" strokeLinecap="round"
                    strokeDasharray={`${1.25 * progressPct} 126`} />
                  <defs><linearGradient id="pg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#3B82F6" /><stop offset="100%" stopColor="#8B5CF6" /></linearGradient></defs>
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">{Math.round(progressPct)}%</span>
              </div>
              <div><div className="text-sm font-medium">处理中...</div><div className="text-xs text-gray-500">{job.num_frames ? `${job.num_frames} 帧` : '准备中'}</div></div>
            </div>
          )}
          {job.status === 'completed' && <div className="mb-4 text-sm text-green-400">&#x2713; 处理完成</div>}
          {job.status === 'failed' && (
            <div className="mb-4 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">处理失败: {job.error_message || '未知错误'}</div>
          )}
          <div className="space-y-1">
            {statusSteps.map((step, i) => (
              <div key={i} className={`flex items-center gap-2 py-1 px-2 rounded text-xs ${i === currentStep ? 'bg-blue-500/10 text-blue-400' : i < currentStep ? 'text-green-400/70' : 'text-gray-600'}`}>
                <span className="w-4 text-center">{i < currentStep ? '✓' : i === currentStep ? '●' : '○'}</span>
                <span>{step.label}</span>
              </div>
            ))}
          </div>
          {job.status === 'completed' && (
            <div className="mt-4 pt-3 border-t border-gray-800 text-xs text-gray-500 space-y-1">
              {job.num_frames && <p>总帧数：{job.num_frames}</p>}
              {job.num_points && <p>点云数量：{(job.num_points/10000).toFixed(1)} 万</p>}
              {job.processing_time_secs && <p>处理耗时：{job.processing_time_secs.toFixed(1)} 秒</p>}
            </div>
          )}
        </div>
        <div className="p-3 border-t border-gray-800 flex gap-2">
          <Link to="/" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300">上传新视频</Link>
          <Link to="/jobs" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300">作业历史</Link>
        </div>
      </div>

      {/* Main Viewer */}
      <div className="flex-1 relative bg-black">
        <div className="absolute inset-0" ref={el => {
          if (el) { const c = el.querySelector('canvas'); if (c && c !== canvasEl) setCanvasEl(c as HTMLCanvasElement); }
        }} />
        {job.status === 'completed' ? (
          <>
            <ViewerCanvas jobId={job.id} pointSize={pointSize} opacity={opacity}
              onPointsReady={handlePointsReady}
              clipPlanes={clipPlanes} boxClip={boxClip}
              showAxes={showAxes} bgColor={bgColor} />
            <Toolbar
              pointSize={pointSize} onPointSizeChange={setPointSize}
              opacity={opacity} onOpacityChange={setOpacity}
              pointCount={pointCount} originalCount={originalCount}
              onVoxelDownsample={doVoxelDownsample}
              onOutlierRemove={doOutlierRemove}
              onReset={doReset}
              measurementMode={measureMode}
              onToggleMeasure={() => { setMeasureMode(!measureMode); measurePtsRef.current=[]; setDistance(null); }}
              distance={distance} onClearMeasure={() => { measurePtsRef.current=[]; setDistance(null); }}
              onResetView={() => {}}
              clipPlanes={clipPlanes} onClipPlanesChange={setClipPlanes}
              boxClip={boxClip} onBoxClipChange={setBoxClip}
              onExport={doExport}
              showAxes={showAxes} onToggleAxes={() => setShowAxes(!showAxes)}
              bgColor={bgColor} onBgColorChange={setBgColor}
            />
          </>
        ) : job.status === 'failed' ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500"><div className="text-center"><div className="text-4xl mb-3">!</div><p>处理失败</p></div></div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center"><div className="text-center"><div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /><p className="text-gray-400 text-sm">正在重建三维模型...</p></div></div>
        )}
      </div>
    </div>
  );
}
