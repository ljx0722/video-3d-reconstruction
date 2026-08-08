import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import * as THREE from 'three';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import Toolbar from './Toolbar';
import type { Job } from '../types';

const POINT_SIZE = 0.008;
const statusSteps = [
  { label: '上传视频' }, { label: '等待处理' }, { label: 'GPU 推理计算中' },
  { label: '导出 3D 模型' }, { label: '重建完成' },
];

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error: jobError } = useSWR<Job>(
    jobId ? `job-${jobId}` : null, () => getJob(jobId!), { refreshInterval: 2000 });

  const [pointSize, setPointSize] = useState(POINT_SIZE);
  const [pointCount, setPointCount] = useState(0);
  const [originalCount, setOriginalCount] = useState(0);
  const [measureMode, setMeasureMode] = useState(false);
  const measurePtsRef = useRef<THREE.Vector3[]>([]);
  const [distance, setDistance] = useState<number | null>(null);

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
      raycaster.setFromCamera(mouse, (window as any).__r3f_camera || new THREE.PerspectiveCamera(50, rect.width / rect.height, 0.1, 100));
      const hits = raycaster.intersectObject(pointsRef.current!);
      if (hits.length > 0) {
        const pt = new THREE.Vector3(hits[0].point.x, hits[0].point.y, hits[0].point.z);
        const next = [...measurePtsRef.current, pt];
        measurePtsRef.current = next;
        if (next.length >= 2) {
          setDistance(next[0].distanceTo(next[1]));
          setMeasureMode(false);
        }
      }
    };
    canvasEl.addEventListener('click', handle);
    return () => canvasEl.removeEventListener('click', handle);
  }, [measureMode, canvasEl]);

  const handlePointsReady = useCallback((mesh: THREE.Points) => {
    pointsRef.current = mesh;
    const pos = mesh.geometry.getAttribute('position');
    if (pos && !originalData.current) {
      originalData.current = { pos: (pos.array as Float32Array).slice(), col: (mesh.geometry.getAttribute('color')?.array as Float32Array)?.slice() || new Float32Array(pos.count * 3) };
      setOriginalCount(pos.count);
      setPointCount(pos.count);
    }
  }, []);

  const doVoxelDownsample = useCallback((voxelSize: number) => {
    if (!originalData.current || !pointsRef.current) return;
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
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(np, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(nc, 3));
    pointsRef.current!.geometry = geo;
    setPointCount(keys.length);
  }, []);

  const doReset = useCallback(() => {
    if (!originalData.current || !pointsRef.current) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(originalData.current.pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(originalData.current.col, 3));
    pointsRef.current.geometry = geo;
    setPointCount(originalData.current.pos.length / 3);
    measurePtsRef.current = [];
    setDistance(null);
  }, []);

  const clearMeasure = useCallback(() => { measurePtsRef.current = []; setDistance(null); }, []);

  const isProcessing = job?.status === 'uploaded' || job?.status === 'processing';
  const progressPct = Math.max(2, Math.min(100, (job?.progress || 0) * 100));
  const currentStep = job?.status === 'completed' ? 4 : isProcessing ? (job?.progress || 0) >= 0.15 ? 2 : 1 : 0;

  if (jobError) return <p className="text-center text-red-400 mt-12">加载作业失败</p>;
  if (!job) return <div className="flex items-center justify-center h-full"><div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;

  const videoUrl = jobId ? `/api/v1/gpu/video/${jobId}` : '';

  return (
    <div className="h-[calc(100vh-7.5rem)] flex">
      {/* Left Panel */}
      <div className="w-64 flex-shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col overflow-hidden">
        {videoUrl && (
          <div className="p-3 border-b border-gray-800">
            <div className="text-xs text-gray-500 mb-2">原始视频</div>
            <video src={videoUrl} controls className="w-full rounded bg-black" preload="metadata" />
          </div>
        )}
        <div className="p-3 flex-1 overflow-auto">
          <div className="text-xs text-gray-500 mb-3">处理进度</div>
          {isProcessing && (
            <div className="mb-4 flex items-center gap-3">
              <div className="relative w-12 h-12 flex-shrink-0">
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
          {job.status === 'completed' && <div className="mb-4 text-sm text-green-400 flex items-center gap-2">&#x2713; 处理完成</div>}
          {job.status === 'failed' && (
            <div className="mb-4 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">
              处理失败: {job.error_message || '未知错误'}
            </div>
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
              {job.num_points && <p>点云数量：{(job.num_points / 10000).toFixed(1)} 万</p>}
              {job.processing_time_secs && <p>处理耗时：{job.processing_time_secs.toFixed(1)} 秒</p>}
            </div>
          )}
        </div>
        <div className="p-3 border-t border-gray-800 flex gap-2">
          <Link to="/" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors">上传新视频</Link>
          <Link to="/jobs" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors">作业历史</Link>
        </div>
      </div>

      {/* Main 3D Viewer */}
      <div className="flex-1 relative bg-black">
        <div className="absolute inset-0" ref={(el) => {
          if (el) { const c = el.querySelector('canvas'); if (c && c !== canvasEl) setCanvasEl(c as HTMLCanvasElement); }
        }} />
        {job.status === 'completed' ? (
          <>
            <ViewerCanvas jobId={job.id} pointSize={pointSize} onPointsReady={handlePointsReady} />
            <Toolbar
              pointSize={pointSize} onPointSizeChange={setPointSize}
              pointCount={pointCount} originalCount={originalCount}
              onVoxelDownsample={doVoxelDownsample} onReset={doReset}
              measurementMode={measureMode}
              onToggleMeasure={() => { setMeasureMode(!measureMode); measurePtsRef.current = []; setDistance(null); }}
              distance={distance} onClearMeasure={clearMeasure} onResetView={() => {}}
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
