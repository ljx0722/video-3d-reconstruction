import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import * as THREE from 'three';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import ControlsPanel from './ControlsPanel';
import { type BoxClip } from './Toolbar';
import type { Job } from '../types';

const POINT_SIZE = 0.004;
const statusSteps = [
  { label: '上传视频' }, { label: '等待处理' }, { label: 'GPU 推理计算中' },
  { label: '导出 3D 模型' }, { label: '重建完成' },
];
const defaultBoxClip: BoxClip = { enabled: false, min: [-1, -0.5, -1], max: [1, 0.5, 1] };

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error: jobError } = useSWR<Job>(
    jobId ? `job-${jobId}` : null, () => getJob(jobId!), { refreshInterval: 2000 });

  // Vis
  const [pointSize, setPointSize] = useState(POINT_SIZE);
  const [opacity, setOpacity] = useState(1);
  const [showAxes, setShowAxes] = useState(false);
  const [showTrajectory, setShowTrajectory] = useState(true);
  const [orthographic, setOrthographic] = useState(false);
  const [colorMode, setColorMode] = useState('rgb');
  const [splatMode, setSplatMode] = useState(false);
  const [brightness, setBrightness] = useState(1.0);
  const [showGrid, setShowGrid] = useState(false);
  const [edlStrength, setEdlStrength] = useState(0.0);

  // Processing
  const [pointCount, setPointCount] = useState(0);
  const [originalCount, setOriginalCount] = useState(0);

  // Clip
  const [boxClip, setBoxClip] = useState<BoxClip>(defaultBoxClip);

  // Measure
  const [measureMode, setMeasureMode] = useState(false);
  const measurePtsRef = useRef<THREE.Vector3[]>([]);
  const [distance, setDistance] = useState<number | null>(null);

  // Streaming
  const [streamBuffer, setStreamBuffer] = useState<Float32Array | null>(null);
  const [streamAppend, setStreamAppend] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Connect WebSocket for live point cloud streaming during processing
  useEffect(() => {
    if (!jobId) return;
    const status = (job as any)?.status;
    if (status !== 'processing' && status !== 'uploaded') return;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/${jobId}`);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        const bytes = new Uint8Array(e.data);
        // Find null byte separator between JSON header and binary
        let nullIdx = -1;
        for (let i = 0; i < Math.min(bytes.length, 200); i++) {
          if (bytes[i] === 0) { nullIdx = i; break; }
        }
        if (nullIdx > 0) {
          const header = JSON.parse(new TextDecoder().decode(bytes.slice(0, nullIdx)));
          if (header.type === 'batch') {
            const fdata = bytes.slice(nullIdx + 1);
            const floats = new Float32Array(fdata.buffer, fdata.byteOffset, fdata.byteLength / 4);
            setStreamBuffer(floats);
            setStreamAppend(header.batch > 0);
          }
        }
      }
    };
    ws.onerror = () => {};  // Fallback to polling-based progress

    return () => { ws.close(); wsRef.current = null; };
  }, [jobId, job?.status]);

  // Refs
  const pointsRef = useRef<THREE.Points | null>(null);
  const originalData = useRef<{ pos: Float32Array; col: Float32Array } | null>(null);
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null);

  // Measure click
  useEffect(() => {
    if (!measureMode || !canvasEl || !pointsRef.current) return;
    const h = (e: MouseEvent) => {
      if (e.button !== 0) return;
      const r = canvasEl.getBoundingClientRect();
      const m = new THREE.Vector2(((e.clientX-r.left)/r.width)*2-1, -((e.clientY-r.top)/r.height)*2+1);
      const rc = new THREE.Raycaster();
      rc.params.Points!.threshold = 0.05;
      rc.setFromCamera(m, new THREE.PerspectiveCamera(50, r.width/r.height, 0.1, 100));
      const hits = rc.intersectObject(pointsRef.current!);
      if (hits.length > 0) {
        measurePtsRef.current.push(hits[0].point.clone());
        if (measurePtsRef.current.length >= 2) {
          setDistance(measurePtsRef.current[0].distanceTo(measurePtsRef.current[1]));
          setMeasureMode(false);
          measurePtsRef.current = [];
        }
      }
    };
    canvasEl.addEventListener('click', h);
    return () => canvasEl.removeEventListener('click', h);
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
          col: col ? (col.array as Float32Array).slice() : new Float32Array(pos.count * 3).fill(1),
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
      for (let i = 0; i < n; i++) {
        const r = col ? Math.round(Math.min(1, col.getX(i)) * 255) : 255;
        const g = col ? Math.round(Math.min(1, col.getY(i)) * 255) : 255;
        const b = col ? Math.round(Math.min(1, col.getZ(i)) * 255) : 255;
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

  const doResetView = useCallback(() => { setOrthographic(false); }, []);

  const doAutoClip = useCallback(() => {
    if (!originalData.current) return;
    const pos = originalData.current.pos;
    let mx=Infinity,Mx=-Infinity,my=Infinity,My=-Infinity,mz=Infinity,Mz=-Infinity;
    for (let i=0;i<pos.length;i+=3) {
      mx=Math.min(mx,pos[i]); Mx=Math.max(Mx,pos[i]);
      my=Math.min(my,pos[i+1]); My=Math.max(My,pos[i+1]);
      mz=Math.min(mz,pos[i+2]); Mz=Math.max(Mz,pos[i+2]);
    }
    const pad = 0.02;
    setBoxClip({ enabled: true, min: [mx-pad,my-pad,mz-pad], max: [Mx+pad,My+pad,Mz+pad] });
  }, []);

  const applyColor = useCallback((mode: string, b: number) => {
    const pts = pointsRef.current;
    if (!pts) return;
    const geo = pts.geometry;
    const pos = geo.getAttribute('position');
    const origCol = originalData.current?.col;
    if (!pos) return;
    const n = pos.count;
    const colors = new Float32Array(n * 3);

    if (mode === 'rgb' && origCol) {
      for (let i = 0; i < n; i++) {
        colors[i*3]=Math.min(1,origCol[i*3]*b);
        colors[i*3+1]=Math.min(1,origCol[i*3+1]*b);
        colors[i*3+2]=Math.min(1,origCol[i*3+2]*b);
      }
    } else if (mode === 'height') {
      let minY=Infinity,maxY=-Infinity;
      for (let i=0;i<n;i++){const y=pos.getY(i);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
      const rng=maxY-minY||1;
      for (let i=0;i<n;i++){
        const t=Math.max(0,Math.min(1,(pos.getY(i)-minY)/rng));
        colors[i*3]=t*0.9+0.05; colors[i*3+1]=(1-t)*0.7+0.1; colors[i*3+2]=(1-t)*0.85+0.1;
      }
    } else if (mode === 'depth') {
      let minZ=Infinity,maxZ=-Infinity;
      for (let i=0;i<n;i++){const z=pos.getZ(i);minZ=Math.min(minZ,z);maxZ=Math.max(maxZ,z);}
      const rng=maxZ-minZ||1;
      for (let i=0;i<n;i++){
        const t=Math.max(0,Math.min(1,(pos.getZ(i)-minZ)/rng));
        colors[i*3]=1-t*0.7; colors[i*3+1]=t*0.9; colors[i*3+2]=0.2;
      }
    } else {
      for (let i=0;i<n;i++){colors[i*3]=colors[i*3+1]=colors[i*3+2]=Math.min(1,0.8*b);}
    }
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.attributes.color.needsUpdate = true;
  }, []);

  useEffect(() => {
    if (pointsRef.current && originalData.current) applyColor(colorMode, brightness);
  }, [colorMode, brightness, applyColor]);

  const isProcessing = (job as any)?.status === 'uploaded' || (job as any)?.status === 'processing';
  const progressPct = Math.max(2, Math.min(100, (job?.progress || 0) * 100));
  const currentStep = (job as any)?.status === 'completed' ? 4 : isProcessing ? (job?.progress||0)>=0.15?2:1 : 0;
  const detailText = ((job as any)?.detail || (job as any)?.settings?._detail || '');

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
          {job.status==='failed'&&<div className="mb-4 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">处理失败: {job.error_message||'未知错误'}</div>}
          <div className="space-y-1">
            {statusSteps.map((step,i)=>(
              <div key={i} className={`flex items-center gap-2 py-1 px-2 rounded text-xs ${i===currentStep?'bg-blue-500/10 text-blue-400':i<currentStep?'text-green-400/70':'text-gray-600'}`}>
                <span className="w-4 text-center">{i<currentStep?'✓':i===currentStep?'●':'○'}</span><span>{step.label}</span>
              </div>
            ))}
          </div>
          {job.status==='completed'&&(
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
        {(job.status==='completed' || (job as any).status==='processing')?(
          <>
            <ViewerCanvas jobId={job.id} pointSize={pointSize} opacity={opacity}
              onPointsReady={handlePointsReady} boxClip={boxClip}
              showAxes={showAxes} orthographic={orthographic} splatMode={splatMode}
              showGrid={showGrid} edlStrength={edlStrength}
              showTrajectory={showTrajectory}
              streamBuffer={(job as any).status === 'processing' ? streamBuffer : null}
              streamAppend={streamAppend}
              liveMode={(job as any).status === 'processing'}
            />
            {(job as any).status !== 'processing' && (
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
              splatMode={splatMode} setSplatMode={setSplatMode}
              brightness={brightness} setBrightness={setBrightness}
              onScreenshot={doScreenshot} onResetView={doResetView}
              showGrid={showGrid} setShowGrid={setShowGrid}
              onAutoClip={doAutoClip}
              edlStrength={edlStrength} setEdlStrength={setEdlStrength}
              showTrajectory={showTrajectory} setShowTrajectory={setShowTrajectory}
            />
            )}
          </>
        ):job.status==='failed'?(
          <div className="absolute inset-0 flex items-center justify-center text-gray-500"><div className="text-center"><div className="text-4xl mb-3">!</div><p>处理失败</p></div></div>
        ):(
          <div className="absolute inset-0 flex items-center justify-center"><div className="text-center"><div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" /><p className="text-gray-400 text-sm">正在重建三维模型...</p></div></div>
        )}
      </div>
    </div>
  );
}
