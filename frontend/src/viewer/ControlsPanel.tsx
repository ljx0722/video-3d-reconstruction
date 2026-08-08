import { useState } from 'react';
import type { ClipPlane, BoxClip } from './Toolbar';

type PanelId = null | 'view' | 'filter' | 'clip' | 'measure' | 'export';

interface CtrlProps {
  pointSize: number; setPointSize: (v: number) => void;
  opacity: number; setOpacity: (v: number) => void;
  pointCount: number; originalCount: number;
  orthographic: boolean; setOrthographic: (v: boolean) => void;
  onVoxelDownsample: (v: number) => void;
  onOutlierRemove: (k: number, s: number) => void;
  onReset: () => void;
  clipPlanes: ClipPlane[]; setClipPlanes: (p: ClipPlane[]) => void;
  boxClip: BoxClip; setBoxClip: (b: BoxClip) => void;
  measureMode: boolean; setMeasureMode: (m: boolean) => void;
  distance: number | null; clearMeasure: () => void;
  onExport: (fmt: string) => void;
  showAxes: boolean; setShowAxes: (v: boolean) => void;
}

const Btn = ({ label, active, icon, onClick }: { label: string; active: boolean; icon: string; onClick: () => void }) => (
  <button onClick={onClick}
    className={`w-9 h-9 rounded-full flex items-center justify-center text-xs transition-all
      ${active ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/30' : 'bg-gray-800/90 text-gray-400 hover:bg-gray-700 hover:text-white'}`}
    title={label}>{icon}</button>
);

export default function ControlsPanel(p: CtrlProps) {
  const [panel, setPanel] = useState<PanelId>(null);
  const [voxelSize, setVoxelSize] = useState(0.02);
  const [outlierK, setOutlierK] = useState(6);
  const [outlierStd, setOutlierStd] = useState(1.0);

  const toggle = (id: PanelId) => setPanel(panel === id ? null : id);

  return (
    <>
      {/* Point count + camera toggle - top left */}
      <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
        <div className="bg-gray-900/80 backdrop-blur rounded-lg px-3 py-1.5 text-xs text-gray-400 border border-gray-800">
          点云 <span className="text-gray-200 font-mono">{(p.pointCount / 10000).toFixed(1)}万</span>
          {p.pointCount !== p.originalCount && (
            <span className="text-gray-600 ml-1">/ {(p.originalCount / 10000).toFixed(1)}万</span>
          )}
        </div>
        <button
          onClick={() => p.setOrthographic(!p.orthographic)}
          className="bg-gray-900/80 backdrop-blur rounded-lg px-2.5 py-1.5 text-xs text-gray-400 border border-gray-800 hover:bg-gray-800 transition-colors"
          title={p.orthographic ? '切换到透视视图' : '切换到平行视图'}
        >
          {p.orthographic ? '平行' : '透视'}
        </button>
      </div>

      {/* Floating circular controls - right side */}
      <div className="absolute right-3 top-1/2 -translate-y-1/2 z-10 flex flex-col gap-2">

        {/* View settings */}
        <Btn icon="⊙" label="显示" active={panel === 'view'} onClick={() => toggle('view')} />
        {panel === 'view' && (
          <ViewPanel pointSize={p.pointSize} setPointSize={p.setPointSize}
            opacity={p.opacity} setOpacity={p.setOpacity}
            showAxes={p.showAxes} setShowAxes={p.setShowAxes}
            pointCount={p.pointCount} originalCount={p.originalCount}
          />
        )}

        {/* Filters */}
        <Btn icon="◇" label="过滤" active={panel === 'filter'} onClick={() => toggle('filter')} />
        {panel === 'filter' && (
          <FilterPanel voxelSize={voxelSize} setVoxelSize={setVoxelSize}
            outlierK={outlierK} setOutlierK={setOutlierK}
            outlierStd={outlierStd} setOutlierStd={setOutlierStd}
            onVoxelDownsample={p.onVoxelDownsample}
            onOutlierRemove={p.onOutlierRemove}
            onReset={p.onReset}
          />
        )}

        {/* Clipping */}
        <Btn icon="⊞" label="裁剪" active={panel === 'clip'} onClick={() => toggle('clip')} />
        {panel === 'clip' && (
          <ClipPanel clipPlanes={p.clipPlanes} setClipPlanes={p.setClipPlanes}
            boxClip={p.boxClip} setBoxClip={p.setBoxClip} />
        )}

        {/* Measure */}
        <Btn icon="⟷" label="测量" active={panel === 'measure' || p.measureMode}
          onClick={() => { p.setMeasureMode(!p.measureMode); if (p.measureMode) p.clearMeasure(); }} />
        {p.distance !== null && (
          <div className="w-9 text-center text-yellow-400 text-[9px] mt-1">
            {(p.distance * 100).toFixed(1)}cm
          </div>
        )}

        {/* Export */}
        <Btn icon="↓" label="导出" active={panel === 'export'} onClick={() => toggle('export')} />
        {panel === 'export' && (
          <ExportPanel onExport={p.onExport} />
        )}
      </div>
    </>
  );
}

/* ── Panel components ──────────────────────────────── */

function ViewPanel({ pointSize, setPointSize, opacity, setOpacity, showAxes, setShowAxes }: any) {
  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-48 text-[11px] border border-gray-800 shadow-xl">
      <div className="text-gray-300 font-medium mb-2 text-xs">显示设置</div>

      <label className="text-gray-500 block mb-1">点大小 <span className="text-gray-700 ml-1">{pointSize.toFixed(3)}</span></label>
      <input type="range" min={0.002} max={0.04} step={0.001} value={pointSize}
        onChange={e => setPointSize(Number(e.target.value))} className="w-full accent-blue-500 mb-2" />

      <label className="text-gray-500 block mb-1">透明度 <span className="text-gray-700 ml-1">{opacity.toFixed(2)}</span></label>
      <input type="range" min={0.1} max={1} step={0.05} value={opacity}
        onChange={e => setOpacity(Number(e.target.value))} className="w-full accent-blue-500 mb-2" />

      <div className="flex gap-1 mt-1">
        <button onClick={() => setShowAxes(!showAxes)}
          className={`flex-1 py-1 rounded text-[10px] ${showAxes ? 'bg-blue-500/30 text-blue-400' : 'bg-gray-800 text-gray-500'}`}>
          坐标轴
        </button>
      </div>
    </div>
  );
}

function FilterPanel({ voxelSize, setVoxelSize, outlierK, setOutlierK, outlierStd, setOutlierStd, onVoxelDownsample, onOutlierRemove, onReset }: any) {
  const [voxelText, setVoxelText] = useState('0.02');
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-56 text-[11px] border border-gray-800 shadow-xl">
      <div className="text-gray-300 font-medium mb-2 text-xs">点云处理</div>

      {/* Voxel downsample */}
      <label className="text-gray-500 block mb-1">体素大小 (m)</label>
      <div className="flex gap-1 mb-2">
        <input type="text" value={voxelText}
          onChange={e => { setVoxelText(e.target.value); const n = Number(e.target.value); if (!isNaN(n) && n > 0) setVoxelSize(n); }}
          className="w-16 bg-gray-800 rounded px-1.5 py-1 text-white border border-gray-700" />
        <button onClick={() => onVoxelDownsample(voxelSize)}
          className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-0.5">降采样</button>
      </div>

      <button onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-gray-500 hover:text-gray-300 text-[10px] mb-1">{showAdvanced ? '收起高级' : '高级 ▼'}</button>

      {showAdvanced && (
        <div className="mb-2">
          <label className="text-gray-500 block mb-1">统计滤波 (K={outlierK}, σ={outlierStd})</label>
          <div className="flex gap-1">
            <input type="number" min={2} max={50} value={outlierK}
              onChange={e => setOutlierK(Number(e.target.value))}
              className="w-10 bg-gray-800 rounded px-1 py-1 text-white border border-gray-700" />
            <input type="number" min={0.1} max={5} step={0.1} value={outlierStd}
              onChange={e => setOutlierStd(Number(e.target.value))}
              className="w-12 bg-gray-800 rounded px-1 py-1 text-white border border-gray-700" />
            <button onClick={() => onOutlierRemove(outlierK, outlierStd)}
              className="flex-1 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded px-2 py-0.5">去噪</button>
          </div>
        </div>
      )}

      <button onClick={onReset}
        className="w-full bg-gray-800 hover:bg-gray-700 text-gray-400 rounded px-2 py-1 text-[10px]">恢复原始点云</button>
    </div>
  );
}

function ClipPanel({ clipPlanes, setClipPlanes, boxClip, setBoxClip }: any) {
  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-56 text-[11px] border border-gray-800 shadow-xl max-h-80 overflow-y-auto">
      <div className="text-gray-300 font-medium mb-2 text-xs">裁剪</div>

      {/* 6 Planes */}
      {clipPlanes.map((p: ClipPlane, i: number) => (
        <div key={i} className={`mb-1.5 p-1.5 rounded ${p.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/30'}`}>
          <div className="flex items-center gap-1 mb-0.5">
            <button onClick={() => {
              const next = [...clipPlanes];
              next[i] = { ...p, enabled: !p.enabled };
              setClipPlanes(next);
            }}
              className={`w-4 h-4 rounded text-[9px] flex items-center justify-center ${p.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-500'}`}>
              {p.enabled ? '✓' : ''}</button>
            <span className="text-gray-400 uppercase">{p.axis}</span>
            <span className="text-[9px] text-gray-500">{p.negative ? '-∞' : '∞'}</span>
          </div>
          <input type="range" min={-3} max={3} step={0.01} value={p.offset}
            onChange={e => {
              const next = [...clipPlanes];
              next[i] = { ...p, offset: Number(e.target.value) };
              setClipPlanes(next);
            }} className="w-full accent-green-500 h-1" />
          <div className="flex justify-between text-[9px] text-gray-600">
            <span>{p.offset.toFixed(2)}</span>
            <button onClick={() => {
              const next = [...clipPlanes];
              next[i] = { ...p, negative: !p.negative };
              setClipPlanes(next);
            }} className="text-gray-500 hover:text-gray-300">翻转</button>
          </div>
        </div>
      ))}

      {/* Box Clip */}
      <div className={`p-1.5 rounded ${boxClip.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/30'}`}>
        <label className="flex items-center gap-1 mb-1">
          <button onClick={() => setBoxClip({ ...boxClip, enabled: !boxClip.enabled })}
            className={`w-4 h-4 rounded text-[9px] flex items-center justify-center ${boxClip.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-500'}`}>
            {boxClip.enabled ? '✓' : ''}</button>
          <span className="text-gray-400">包围盒裁剪</span>
        </label>
        {boxClip.enabled && (
          <div className="grid grid-cols-2 gap-1 text-[9px]">
            {(['min', 'max'] as const).flatMap(mode =>
              (['x', 'y', 'z'] as const).map(axis => {
                const idx = { x: 0, y: 1, z: 2 }[axis];
                return (
                  <div key={`${mode}-${axis}`} className="flex items-center gap-0.5">
                    <span className="text-gray-600 w-5">{mode}{axis}</span>
                    <input type="number" min={-10} max={10} step={0.01} value={boxClip[mode][idx]}
                      onChange={e => {
                        const arr = [...boxClip[mode]] as [number, number, number];
                        arr[idx] = Number(e.target.value);
                        setBoxClip({ ...boxClip, [mode]: arr });
                      }}
                      className="flex-1 bg-gray-800 rounded px-1 py-0.5 text-white border border-gray-700 w-12" />
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ExportPanel({ onExport }: { onExport: (fmt: string) => void }) {
  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-36 text-[11px] border border-gray-800 shadow-xl">
      <div className="text-gray-300 font-medium mb-2 text-xs">导出格式</div>
      <div className="flex flex-col gap-1">
        {[
          ['PLY', '点云 (含颜色)'],
          ['XYZ', '纯坐标'],
          ['GLB', '3D 模型'],
        ].map(([fmt, desc]) => (
          <button key={fmt} onClick={() => onExport(fmt)}
            className="flex justify-between bg-gray-800 hover:bg-gray-700 rounded px-2 py-1.5 text-gray-400 hover:text-white transition-colors text-[10px]">
            <span className="font-mono">.{fmt.toLowerCase()}</span>
            <span className="text-gray-600">{desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
