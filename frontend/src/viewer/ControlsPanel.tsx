import { useState } from 'react';
import type { ClipPlane, BoxClip } from './Toolbar';

type PanelId = null | 'view' | 'color' | 'filter' | 'clip' | 'measure' | 'export';

interface CtrlProps {
  pointSize: number; setPointSize: (v: number) => void;
  opacity: number; setOpacity: (v: number) => void;
  pointCount: number; originalCount: number;
  orthographic: boolean; setOrthographic: (v: boolean) => void;
  onVoxelDownsample: (v: number) => void;
  onFastOutlierRemove: (k: number, s: number) => void;
  onReset: () => void;
  clipPlanes: ClipPlane[]; setClipPlanes: (p: ClipPlane[]) => void;
  boxClip: BoxClip; setBoxClip: (b: BoxClip) => void;
  measureMode: boolean; setMeasureMode: (m: boolean) => void;
  distance: number | null; clearMeasure: () => void;
  onExport: (fmt: string) => void;
  showAxes: boolean; setShowAxes: (v: boolean) => void;
  colorMode: string; setColorMode: (m: string) => void;
  splatMode: boolean; setSplatMode: (v: boolean) => void;
  brightness: number; setBrightness: (v: number) => void;
  onScreenshot: () => void;
  onResetView: () => void;
  showGrid: boolean; setShowGrid: (v: boolean) => void;
  onAutoClip: () => void;
}

const Btn = ({ label, active, icon, onClick }: { label: string; active: boolean; icon: string; onClick: () => void }) => (
  <button onClick={onClick}
    className={`w-9 h-9 rounded-full flex items-center justify-center text-xs transition-all duration-200
      ${active ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/30 scale-110' : 'bg-gray-800/90 text-gray-400 hover:bg-gray-700 hover:text-white hover:scale-105'}`}
    title={label}>{icon}</button>
);

export default function ControlsPanel(p: CtrlProps) {
  const [panel, setPanel] = useState<PanelId>(null);
  const [voxelSize, setVoxelSize] = useState(0.02);
  const [outlierK, setOutlierK] = useState(20);
  const [outlierStd, setOutlierStd] = useState(1.0);

  const toggle = (id: PanelId) => setPanel(panel === id ? null : id);

  return (
    <>
      {/* Top-left info bar */}
      <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
        <div className="bg-gray-900/80 backdrop-blur rounded-lg px-3 py-1.5 text-xs text-gray-400 border border-gray-800">
          点云 <span className="text-gray-200 font-mono">{(p.pointCount / 10000).toFixed(1)}万</span>
          {p.pointCount !== p.originalCount && (
            <span className="text-gray-600 ml-1">/ {(p.originalCount / 10000).toFixed(1)}万</span>
          )}
        </div>
        <button onClick={() => p.setOrthographic(!p.orthographic)}
          className="bg-gray-900/80 backdrop-blur rounded-lg px-2.5 py-1.5 text-xs text-gray-400 border border-gray-800 hover:bg-gray-800">
          {p.orthographic ? '平行' : '透视'}
        </button>
        <button onClick={p.onScreenshot}
          className="bg-gray-900/80 backdrop-blur rounded-lg px-2.5 py-1.5 text-xs text-gray-400 border border-gray-800 hover:bg-gray-800" title="截图">
          📷
        </button>
      </div>

      {/* Right-side circular controls */}
      <div className="absolute right-3 top-1/2 -translate-y-1/2 z-10 flex flex-col gap-2">
        {/* View / Display */}
        <Btn icon="⊙" label="显示设置" active={panel === 'view'} onClick={() => toggle('view')} />
        {panel === 'view' && <ViewPanel {...p} />}

        {/* Color Mode */}
        <Btn icon="◉" label="着色模式" active={panel === 'color'} onClick={() => toggle('color')} />
        {panel === 'color' && <ColorPanel colorMode={p.colorMode} setColorMode={p.setColorMode}
          brightness={p.brightness} setBrightness={p.setBrightness}
          splatMode={p.splatMode} setSplatMode={p.setSplatMode} />}

        {/* Processing / Filters */}
        <Btn icon="◇" label="点云处理" active={panel === 'filter'} onClick={() => toggle('filter')} />
        {panel === 'filter' && <FilterPanel
          voxelSize={voxelSize} setVoxelSize={setVoxelSize}
          outlierK={outlierK} setOutlierK={setOutlierK}
          outlierStd={outlierStd} setOutlierStd={setOutlierStd}
          onVoxelDownsample={p.onVoxelDownsample}
          onOutlierRemove={p.onFastOutlierRemove}
          onReset={p.onReset} />}

        {/* Clipping */}
        <Btn icon="⊞" label="裁剪工具" active={panel === 'clip'} onClick={() => toggle('clip')} />
        {panel === 'clip' && <ClipPanel clipPlanes={p.clipPlanes} setClipPlanes={p.setClipPlanes}
          boxClip={p.boxClip} setBoxClip={p.setBoxClip} onAutoClip={p.onAutoClip} />}

        {/* Measure */}
        <Btn icon="⟷" label="测量" active={panel === 'measure' || p.measureMode}
          onClick={() => { p.setMeasureMode(!p.measureMode); if (p.measureMode) p.clearMeasure(); }} />
        {p.distance !== null && (
          <div className="w-9 text-center text-yellow-400 text-[9px] -mt-1">
            {(p.distance * 100).toFixed(1)}cm
          </div>
        )}

        {/* Grid */}
        <Btn icon="⊡" label="网格" active={p.showGrid} onClick={() => p.setShowGrid(!p.showGrid)} />

        {/* Snap / Reset View */}
        <Btn icon="⌂" label="复位视图" active={false} onClick={p.onResetView} />

        {/* Export */}
        <Btn icon="↓" label="导出" active={panel === 'export'} onClick={() => toggle('export')} />
        {panel === 'export' && <ExportPanel onExport={p.onExport} />}
      </div>
    </>
  );
}

/* ── View Panel ───────────────────────────────────── */
function ViewPanel({ pointSize, setPointSize, opacity, setOpacity, showAxes, setShowAxes }: any) {
  return (
    <Card title="显示设置">
      <label className="text-gray-500 block mb-1">
        点大小 <span className="text-gray-600">{pointSize.toFixed(4)}</span>
      </label>
      <input type="range" min={0.001} max={0.05} step={0.001} value={pointSize}
        onChange={e => setPointSize(Number(e.target.value))} className="w-full accent-blue-500 mb-3" />

      <label className="text-gray-500 block mb-1">
        透明度 <span className="text-gray-600">{opacity.toFixed(2)}</span>
      </label>
      <input type="range" min={0.1} max={1} step={0.05} value={opacity}
        onChange={e => setOpacity(Number(e.target.value))} className="w-full accent-blue-500 mb-3" />

      <div className="flex gap-1">
        <button onClick={() => setShowAxes(!showAxes)}
          className={`flex-1 py-1 rounded text-[10px] ${showAxes ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
          {showAxes ? '✓ 坐标轴' : '坐标轴'}
        </button>
      </div>
    </Card>
  );
}

/* ── Color Panel ──────────────────────────────────── */
function ColorPanel({ colorMode, setColorMode, brightness, setBrightness, splatMode, setSplatMode }: any) {
  return (
    <Card title="着色模式">
      <div className="grid grid-cols-3 gap-1 mb-3">
        {[
          ['rgb', '原始色'],
          ['height', '高度'],
          ['depth', '深度'],
          ['confidence', '置信度'],
          ['white', '白色'],
          ['normal', '法线'],
        ].map(([k, label]) => (
          <button key={k} onClick={() => setColorMode(k)}
            className={`py-1 rounded text-[10px] ${colorMode === k ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'bg-gray-800/50 text-gray-500'}`}>
            {label}
          </button>
        ))}
      </div>

      <label className="text-gray-500 block mb-1">亮度 <span className="text-gray-600">{brightness.toFixed(1)}</span></label>
      <input type="range" min={0.3} max={2} step={0.1} value={brightness}
        onChange={e => setBrightness(Number(e.target.value))} className="w-full accent-blue-500 mb-3" />

      <div className="flex gap-1">
        <button onClick={() => setSplatMode(!splatMode)}
          className={`flex-1 py-1 rounded text-[10px] ${splatMode ? 'bg-purple-500/20 text-purple-400' : 'bg-gray-800/50 text-gray-500'}`}>
          {splatMode ? '✓ 高斯显示' : '高斯显示'}
        </button>
      </div>
    </Card>
  );
}

/* ── Filter Panel ─────────────────────────────────── */
function FilterPanel({ voxelSize, setVoxelSize, outlierK, setOutlierK, outlierStd, setOutlierStd, onVoxelDownsample, onOutlierRemove, onReset }: any) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <Card title="点云处理">
      <label className="text-gray-500 block mb-1">体素降采样</label>
      <div className="flex gap-1 mb-3">
        <input type="number" min={0.005} max={0.5} step={0.005} value={voxelSize}
          onChange={e => setVoxelSize(Number(e.target.value))}
          className="w-16 bg-gray-800 rounded px-1.5 py-1 text-white text-xs border border-gray-700" />
        <button onClick={() => onVoxelDownsample(voxelSize)}
          className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-0.5 text-[10px]">执行降采样</button>
      </div>

      <button onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-gray-500 hover:text-gray-300 text-[10px] mb-2">{showAdvanced ? '▼ 收起去噪' : '▶ 统计去噪'}</button>

      {showAdvanced && (
        <div className="mb-2">
          <div className="flex gap-1 mb-1">
            <span className="text-gray-500 text-[9px]">K近邻</span>
            <input type="number" min={5} max={100} value={outlierK}
              onChange={e => setOutlierK(Number(e.target.value))}
              className="w-12 bg-gray-800 rounded px-1 py-0.5 text-white text-[10px] border border-gray-700" />
            <span className="text-gray-500 text-[9px]">标准差</span>
            <input type="number" min={0.1} max={3} step={0.1} value={outlierStd}
              onChange={e => setOutlierStd(Number(e.target.value))}
              className="w-10 bg-gray-800 rounded px-1 py-0.5 text-white text-[10px] border border-gray-700" />
          </div>
          <button onClick={() => onOutlierRemove(outlierK, outlierStd)}
            className="w-full bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded px-2 py-1 text-[10px]">执行去噪</button>
        </div>
      )}

      <button onClick={onReset}
        className="w-full bg-gray-800/50 hover:bg-gray-700/50 text-gray-400 rounded px-2 py-1 text-[10px] mt-1 border border-gray-700/50">
        恢复原始点云
      </button>
    </Card>
  );
}

/* ── Clip Panel ───────────────────────────────────── */
function ClipPanel({ clipPlanes, setClipPlanes, boxClip, setBoxClip, onAutoClip }: any) {
  return (
    <Card title="裁剪工具">
      <button onClick={onAutoClip}
        className="w-full bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-1 text-[10px] mb-2 border border-blue-500/20">
        ▣ 自动包围盒裁剪
      </button>

      <div className="text-gray-500 text-[10px] mb-1">平面裁剪</div>
      {clipPlanes.map((p: ClipPlane, i: number) => (
        <div key={i} className={`mb-1 p-1.5 rounded text-[10px] ${p.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/30'}`}>
          <div className="flex items-center gap-1 mb-0.5">
            <button onClick={() => {
              const n = [...clipPlanes]; n[i] = { ...p, enabled: !p.enabled }; setClipPlanes(n);
            }} className={`w-4 h-4 rounded-[3px] text-[9px] flex items-center justify-center ${p.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-400'}`}>
              {p.enabled ? '✓' : ''}</button>
            <span className="text-gray-400 font-mono">{p.axis}{p.negative ? '⁻' : '⁺'}</span>
          </div>
          <input type="range" min={-5} max={5} step={0.005} value={p.offset}
            onChange={e => { const n = [...clipPlanes]; n[i] = { ...p, offset: Number(e.target.value) }; setClipPlanes(n); }}
            className="w-full accent-green-500 h-1" />
          <div className="flex justify-between text-[9px] text-gray-600">
            <span>{p.offset.toFixed(2)}m</span>
            <button onClick={() => { const n = [...clipPlanes]; n[i] = { ...p, negative: !p.negative }; setClipPlanes(n); }}
              className="text-gray-500 hover:text-gray-300 px-1 rounded">翻转</button>
          </div>
        </div>
      ))}

      <div className={`mt-2 p-1.5 rounded text-[10px] ${boxClip.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/30'}`}>
        <div className="flex items-center gap-1 mb-1">
          <button onClick={() => setBoxClip({ ...boxClip, enabled: !boxClip.enabled })}
            className={`w-4 h-4 rounded-[3px] text-[9px] flex items-center justify-center ${boxClip.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-400'}`}>
            {boxClip.enabled ? '✓' : ''}</button>
          <span className="text-gray-400">包围盒</span>
        </div>
        {boxClip.enabled && (
          <div className="grid grid-cols-2 gap-x-1 gap-y-0.5">
            {(['min','max'] as const).flatMap(m => ['x','y','z'].map(a => {
              const idx = {x:0,y:1,z:2}[a as 'x'|'y'|'z'];
              return (
                <div key={`${m}-${a}`} className="flex items-center gap-0.5">
                  <span className="text-gray-600 w-5">{m}{a}</span>
                  <input type="number" min={-20} max={20} step={0.01} value={boxClip[m][idx]}
                    onChange={e => {
                      const arr = [...boxClip[m]] as [number,number,number]; arr[idx]=Number(e.target.value);
                      setBoxClip({...boxClip,[m]:arr});
                    }} className="flex-1 bg-gray-800 rounded px-1 py-0.5 text-white border border-gray-700 w-12 text-[9px]" />
                </div>
              );
            }))}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ── Export Panel ─────────────────────────────────── */
function ExportPanel({ onExport }: { onExport: (fmt: string) => void }) {
  return (
    <Card title="导出">
      <div className="flex flex-col gap-1">
        {[['PLY','点云 (含颜色)'],['XYZ','纯坐标 (.xyz)'],['GLB','3D 模型 (.glb)'],['LAS','激光雷达 (.las)']].map(([fmt,desc]) => (
          <button key={fmt} onClick={() => onExport(fmt)}
            className="flex justify-between bg-gray-800/50 hover:bg-gray-700/50 rounded px-2 py-1.5 text-gray-400 hover:text-white transition-colors text-[10px]">
            <span className="font-mono">.{fmt.toLowerCase()}</span><span className="text-gray-600">{desc}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

/* ── Card wrapper ─────────────────────────────────── */
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-52 text-[11px] border border-gray-800 shadow-2xl max-h-[70vh] overflow-y-auto">
      <div className="text-gray-300 font-semibold mb-2 text-xs border-b border-gray-800 pb-1.5">{title}</div>
      {children}
    </div>
  );
}
