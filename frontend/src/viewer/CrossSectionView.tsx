import { useState, useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';

type PlaneType = 'XY' | 'XZ' | 'YZ';

interface Props {
  positions: Float32Array | null;
  colors: Float32Array | null;
}

export default function CrossSectionView({ positions, colors }: Props) {
  const [plane, setPlane] = useState<PlaneType>('XZ');
  const [slicePos, setSlicePos] = useState(0);
  const [thickness, setThickness] = useState(0.02);
  const [computeSlice, setComputeSlice] = useState(0);
  const [computeThick, setComputeThick] = useState(0.02);
  const rafRef = useRef(0);
  const setPosThrottled = (v: number) => {
    setSlicePos(v);
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => setComputeSlice(v));
  };
  const setThickThrottled = (v: number) => {
    setThickness(v);
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => setComputeThick(v));
  };
  const bbox = useMemo(() => {
    if (!positions || positions.length === 0) return null;
    let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity,minZ=Infinity,maxZ=-Infinity;
    for (let i=0; i<positions.length; i+=3) {
      const x=positions[i], y=positions[i+1], z=positions[i+2];
      if(x<minX)minX=x; if(x>maxX)maxX=x;
      if(y<minY)minY=y; if(y>maxY)maxY=y;
      if(z<minZ)minZ=z; if(z>maxZ)maxZ=z;
    }
    return { minX, maxX, minY, maxY, minZ, maxZ };
  }, [positions]);

  // Filtered points near the slice plane
  const filtered = useMemo(() => {
    if (!positions || !bbox) return null;
    const axisIdx = plane === 'YZ' ? 0 : plane === 'XZ' ? 1 : 2;
    const mins = [bbox.minX, bbox.minY, bbox.minZ];
    const maxs = [bbox.maxX, bbox.maxY, bbox.maxZ];
    const center = (mins[axisIdx] + maxs[axisIdx]) / 2;
    const halfRange = (maxs[axisIdx] - mins[axisIdx]) / 2 || 0.01;
    const worldPos = center + computeSlice * halfRange;
    const halfThick = computeThick * (maxs[axisIdx] - mins[axisIdx]) / 2;

    const kept: number[] = [];
    const keptCol: number[] = [];
    for (let i = 0; i < positions.length; i += 3) {
      const val = axisIdx === 0 ? positions[i] : axisIdx === 1 ? positions[i+1] : positions[i+2];
      if (Math.abs(val - worldPos) < halfThick) {
        kept.push(positions[i], positions[i+1], positions[i+2]);
        if (colors && colors.length > i + 2) {
          keptCol.push(colors[i], colors[i+1], colors[i+2]);
        } else {
          keptCol.push(0.6, 0.6, 0.6);
        }
      }
    }

    return {
      pos: new Float32Array(kept),
      col: new Float32Array(keptCol),
      count: kept.length / 3,
    };
  }, [positions, colors, bbox, plane, computeSlice, computeThick]);

  // Camera setup for each plane (orthographic, looking perpendicular)
  const extent = bbox ? Math.max(bbox.maxX-bbox.minX, bbox.maxY-bbox.minY, bbox.maxZ-bbox.minZ) || 1 : 1;
  const center = bbox
    ? [(bbox.minX+bbox.maxX)/2, (bbox.minY+bbox.maxY)/2, (bbox.minZ+bbox.maxZ)/2] as [number,number,number]
    : [0,0,0] as [number,number,number];

  const camPos: [number,number,number] = plane === 'XY'
    ? [center[0], center[1] + extent, center[2]]
    : plane === 'XZ'
    ? [center[0], center[1], center[2] + extent]
    : [center[0] + extent, center[1], center[2]];

  const camUp: [number,number,number] = plane === 'XY' ? [0,0,-1] : [0,1,0];

  return (
    <div className="absolute left-3 bottom-3 z-10">
      <div className="bg-gray-900/95 backdrop-blur rounded-lg border border-gray-700 overflow-hidden shadow-xl"
        style={{ width: 200, height: 240 }}>
        {/* Header: plane selector */}
        <div className="flex items-center border-b border-gray-700 bg-gray-950/60">
          {(['XY','XZ','YZ'] as PlaneType[]).map(p => (
            <button key={p} onClick={() => setPlane(p)}
              className={`flex-1 py-1 text-[10px] font-mono transition-colors
                ${plane===p ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'}`}>
              {p}
            </button>
          ))}
          <span className="text-[9px] text-gray-600 pr-1.5">{filtered?.count ?? 0} pts</span>
        </div>

        {/* Mini canvas */}
        <div style={{ width: 200, height: 160 }}>
          {bbox && filtered && filtered.pos.length > 0 ? (
            <Canvas orthographic camera={{ position: camPos, up: camUp, zoom: 35, near: 0.001, far: 500 }} frameloop="demand">
              <ambientLight intensity={1.2} />
              <SlicePoints positions={filtered.pos} colors={filtered.col} extent={extent} />
              <OrbitControls
                enableRotate={false}
                enablePan={true}
                enableZoom={true}
                zoomSpeed={0.5}
                target={center}
              />
            </Canvas>
          ) : (
            <div className="w-full h-full flex items-center justify-center text-gray-600 text-[10px]">
              {!bbox ? '加载中...' : '无数据'}
            </div>
          )}
        </div>

        {/* Sliders */}
        <div className="px-2 py-1 space-y-1">
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-gray-500 w-7">位置</span>
            <input type="range" min={-1} max={1} step={0.01} value={slicePos}
              onChange={e => setPosThrottled(Number(e.target.value))} className="flex-1 accent-blue-500 h-1" />
            <span className="text-[9px] text-gray-500 w-6 text-right">{slicePos.toFixed(1)}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-gray-500 w-7">厚度</span>
            <input type="range" min={0.005} max={0.15} step={0.005} value={thickness}
              onChange={e => setThickThrottled(Number(e.target.value))} className="flex-1 accent-blue-500 h-1" />
            <span className="text-[9px] text-gray-500 w-6 text-right">{thickness.toFixed(3)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SlicePoints({ positions, colors, extent }: { positions: Float32Array; colors: Float32Array; extent: number }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return g;
  }, [positions, colors]);

  const size = extent * 0.003;

  return (
    <points geometry={geom}>
      <pointsMaterial size={size} vertexColors sizeAttenuation={false} />
    </points>
  );
}
