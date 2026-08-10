import { useState } from 'react';
import * as THREE from 'three';
import type { BoxClip } from './Toolbar';

type PanelId = null | 'view' | 'color' | 'filter' | 'clip' | 'measure' | 'export';

interface CtrlProps {
  pointSize: number; setPointSize: (v: number) => void;
  opacity: number; setOpacity: (v: number) => void;
  pointCount: number; originalCount: number;
  orthographic: boolean; setOrthographic: (v: boolean) => void;
  onVoxelDownsample: (v: number) => void;
  onFastOutlierRemove: (k: number, s: number) => void;
  onReset: () => void;
  boxClip: BoxClip; setBoxClip: (b: BoxClip) => void;
  measureMode: boolean; setMeasureMode: (m: boolean) => void;
  distance: number | null; clearMeasure: () => void;
  onExport: (fmt: string) => void;
  showAxes: boolean; setShowAxes: (v: boolean) => void;
  showTrajectory: boolean; setShowTrajectory: (v: boolean) => void;
  colorMode: string; setColorMode: (m: string) => void;
  brightness: number; setBrightness: (v: number) => void;
  onScreenshot: () => void;
  onResetView: () => void;
  showGrid: boolean; setShowGrid: (v: boolean) => void;
  edlStrength: number; setEdlStrength: (v: number) => void;
  orientMode?: boolean; setOrientMode?: (v: boolean) => void;
  orientMarkers?: THREE.Vector3[] | null;
  orientPlane?: { normal: THREE.Vector3; center: THREE.Vector3 } | null;
  onApplyOrient?: () => void;
  onCancelOrient?: () => void;
  lassoEnabled?: boolean; setLassoEnabled?: (v: boolean) => void;
  selectedCount?: number;
  annotations?: any[]; onClearAnnotations?: () => void;
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
        {p.setLassoEnabled && (
        <button onClick={() => p.setLassoEnabled?.(!p.lassoEnabled)}
          className={`bg-gray-900/80 backdrop-blur rounded-lg px-2.5 py-1.5 text-xs border hover:bg-gray-800
            ${p.lassoEnabled ? 'text-blue-400 border-blue-500/30' : 'text-gray-400 border-gray-800'}`} title="Ctrl+点击圈选">
          {p.lassoEnabled && (p.selectedCount ?? 0) > 0 ? `✂ ${p.selectedCount}` : '✂'}
        </button>
        )}
        {(p.setOrientMode || p.onCancelOrient) && (
        <button onClick={() => {
          if (p.orientPlane) { if (p.onCancelOrient) p.onCancelOrient(); }
          else if (p.setOrientMode) p.setOrientMode(!p.orientMode);
          else if (p.onCancelOrient) p.onCancelOrient();
        }}
          className={`bg-gray-900/80 backdrop-blur rounded-lg px-2.5 py-1.5 text-xs border hover:bg-gray-800
            ${(p.orientMode || p.orientPlane) ? 'text-blue-400 border-blue-500/30' : 'text-gray-400 border-gray-800'}`} title="方向校正">
          {(p.orientMode || p.orientPlane) ? '⟴ 定向中' : '⟴ 定向'}
        </button>
        )}
        {/* Quick view presets */}
        <ViewPresets />
      </div>

      {/* Right-side circular controls */}
      <div className="absolute right-3 top-1/2 -translate-y-1/2 z-10 flex flex-col gap-2">
        {/* View / Display */}
        <Btn icon="⊙" label="显示设置" active={panel === 'view'} onClick={() => toggle('view')} />
        {panel === 'view' && <ViewPanel {...p} />}

        {/* Color Mode */}
        <Btn icon="◉" label="着色模式" active={panel === 'color'} onClick={() => toggle('color')} />
        {panel === 'color' && <ColorPanel colorMode={p.colorMode} setColorMode={p.setColorMode}
          brightness={p.brightness} setBrightness={p.setBrightness} />}

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
        <Btn icon="⊞" label="包围盒裁剪" active={panel === 'clip'} onClick={() => toggle('clip')} />
        {panel === 'clip' && <ClipPanel
          boxClip={p.boxClip} setBoxClip={p.setBoxClip} />}

        {/* Measure */}
        <Btn icon="⟷" label="测量" active={panel === 'measure' || p.measureMode}
          onClick={() => { p.setMeasureMode(!p.measureMode); if (p.measureMode) p.clearMeasure(); }} />
        {p.distance !== null && (
          <div className="w-9 text-center text-yellow-400 text-[9px] -mt-1">
            {(p.distance * 100).toFixed(1)}cm
          </div>
        )}

        {/* Orient (3-point ground plane) */}
        <Btn icon="⟴" label="方向校正" active={!!p.orientMode || !!p.orientPlane}
          onClick={() => {
            if (p.orientPlane) return; // has pending result, don't re-enter
            if (p.onCancelOrient) p.onCancelOrient();
            else if (p.setOrientMode) p.setOrientMode(!p.orientMode);
          }} />
        {(p.orientMode || p.orientPlane) && (
          <OrientPanel
            orientMode={!!p.orientMode}
            markerCount={p.orientMarkers?.length ?? 0}
            orientPlane={p.orientPlane ?? null}
            onApply={p.onApplyOrient ?? (() => {})}
            onCancel={p.onCancelOrient ?? (() => {})}
          />
        )}

        {/* Export */}
        <Btn icon="↓" label="导出" active={panel === 'export'} onClick={() => toggle('export')} />
        {panel === 'export' && <ExportPanel onExport={p.onExport} />}
      </div>
    </>
  );
}

/* ── View Panel (merged grid + reset) ─────────────────── */
function ViewPanel({ pointSize, setPointSize, opacity, setOpacity, showAxes, setShowAxes, showTrajectory, setShowTrajectory, edlStrength, setEdlStrength, showGrid, setShowGrid, onResetView }: any) {
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

      <div className="flex gap-1 mb-2">
        <button onClick={() => setShowAxes(!showAxes)}
          className={`flex-1 py-1 rounded text-[10px] ${showAxes ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
          坐标轴
        </button>
        {setShowTrajectory && (
        <button onClick={() => setShowTrajectory(!showTrajectory)}
          className={`flex-1 py-1 rounded text-[10px] ${showTrajectory ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
          相机轨迹
        </button>
        )}
      </div>

      <div className="flex gap-1 mb-3">
        <button onClick={() => setShowGrid(!showGrid)}
          className={`flex-1 py-1 rounded text-[10px] ${showGrid ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
          {showGrid ? '网格 ✓' : '网格'}
        </button>
        <button onClick={onResetView}
          className="flex-1 py-1 rounded text-[10px] bg-gray-800/50 text-gray-500 hover:bg-gray-700/50">
          复位视图
        </button>
      </div>

      <label className="text-gray-500 block mb-1">
        EDL <span className="text-gray-600">{(edlStrength ?? 0).toFixed(1)}</span>
      </label>
      <input type="range" min={0} max={1} step={0.1} value={edlStrength ?? 0}
        onChange={e => setEdlStrength(Number(e.target.value))} className="w-full accent-blue-500 mb-1" />
    </Card>
  );
}

/* ── Color Panel (gaussian toggle removed) ─────────── */
function ColorPanel({ colorMode, setColorMode, brightness, setBrightness }: any) {
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
        onChange={e => setBrightness(Number(e.target.value))} className="w-full accent-blue-500" />
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
function ClipPanel({ boxClip, setBoxClip }: any) {
  const doHalfClip = (axis: 'x'|'y'|'z', sign: 1|-1) => {
    // Dispatch event that ViewerCanvas handles
    window.dispatchEvent(new CustomEvent('clip-preset', { detail: { axis, sign } }));
  };
  return (
    <Card title="包围盒裁剪">
      <div className="flex gap-0.5 mb-2">
        {[
          ['X-', 'x', -1], ['X+', 'x', 1],
          ['Y-', 'y', -1], ['Y+', 'y', 1],
          ['Z-', 'z', -1], ['Z+', 'z', 1],
        ].map(([label, ax, sign]) => (
          <button key={label} onClick={() => doHalfClip(ax as 'x'|'y'|'z', sign as 1|-1)}
            className="flex-1 py-0.5 rounded bg-gray-800/50 hover:bg-blue-500/20 text-[9px] text-gray-500 hover:text-blue-400 border border-gray-700/50">
            {label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-1 mb-2">
        <button onClick={() => setBoxClip({ ...boxClip, enabled: !boxClip.enabled })}
          className={`w-4 h-4 rounded-[3px] text-[9px] flex items-center justify-center ${boxClip.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-400'}`}>
          {boxClip.enabled ? '✓' : ''}</button>
        <span className="text-gray-400 text-[10px]">启用裁剪盒（拖拽彩色方块调节）</span>
      </label>

      {boxClip.enabled && (
        <div className="grid grid-cols-2 gap-x-1 gap-y-0.5">
          {(['min','max'] as const).flatMap(m => ['x','y','z'].map(a => {
            const idx = {x:0,y:1,z:2}[a as 'x'|'y'|'z'];
            return (
              <div key={`${m}-${a}`} className="flex items-center gap-0.5">
                <span className="text-gray-600 w-5 text-[9px]">{m}{a}</span>
                <input type="number" min={-50} max={50} step={0.01} value={Number(boxClip[m][idx]).toFixed(2)}
                  onChange={e => {
                    const v = Number(e.target.value);
                    if (isNaN(v)) return;
                    const arr = [...boxClip[m]] as [number,number,number]; arr[idx]=v;
                    setBoxClip({...boxClip,[m]:arr});
                  }} className="flex-1 bg-gray-800 rounded px-1 py-0.5 text-white border border-gray-700 text-[9px]" />
              </div>
            );
          }))}
        </div>
      )}
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

/* ── Orient Panel ──────────────────────────────────── */
function OrientPanel({ orientMode, markerCount, orientPlane, onApply, onCancel }: {
  orientMode: boolean; markerCount: number; orientPlane: { normal: THREE.Vector3; center: THREE.Vector3 } | null;
  onApply: () => void; onCancel: () => void;
}) {
  return (
    <Card title="方向校正">
      {orientMode ? (
        <div className="space-y-2">
          <p className="text-gray-400 text-[10px]">在地面区域点选 <strong>3 个点</strong>，系统自动拟合地平面并校正方向。</p>
          <div className="flex gap-1">
            {[0,1,2].map(i => (
              <div key={i} className={`flex-1 h-6 rounded flex items-center justify-center text-[10px] font-mono
                ${i < markerCount ? 'bg-blue-500/30 text-blue-300 border border-blue-400/50' : 'bg-gray-800 text-gray-600 border border-gray-700'}`}>
                {i < markerCount ? `P${i+1}` : '○'}
              </div>
            ))}
          </div>
          <button onClick={onCancel}
            className="w-full bg-gray-800/50 hover:bg-gray-700/50 text-gray-400 rounded px-2 py-1 text-[10px] border border-gray-700/50">
            取消
          </button>
        </div>
      ) : orientPlane ? (
        <div className="space-y-2">
          <p className="text-green-400/80 text-[10px]">✓ 地平面已拟合</p>
          <div className="text-gray-500 text-[9px] space-y-0.5">
            <p>法线: ({orientPlane.normal.x.toFixed(2)}, {orientPlane.normal.y.toFixed(2)}, {orientPlane.normal.z.toFixed(2)})</p>
          </div>
          <div className="flex gap-1">
            <button onClick={onApply}
              className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-1 text-[10px] border border-blue-500/20">
              应用旋转
            </button>
            <button onClick={onCancel}
              className="flex-1 bg-gray-800/50 hover:bg-gray-700/50 text-gray-400 rounded px-2 py-1 text-[10px] border border-gray-700/50">
              放弃
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

/* ── View presets ──────────────────────────────── */
function ViewPresets() {
  return (
    <div className="flex items-center gap-0.5 bg-gray-900/80 backdrop-blur rounded-lg px-1 py-0.5 border border-gray-800">
      {[
        ['前', 0,0,1], ['后', 0,0,-1], ['左', -1,0,0], ['右', 1,0,0], ['上', 0,1,0], ['下', 0,-1,0],
      ].map(([label, x, y, z]) => (
        <button key={String(label)} onClick={() => {
          const d = 5;
          window.dispatchEvent(new CustomEvent('view-preset', { detail: { pos: [(x as number)*d, (y as number)*d, (z as number)*d] } }));
        }}
          className="text-[9px] text-gray-500 hover:text-gray-200 hover:bg-gray-700/50 rounded px-1"
          title={`视图: ${label}`}>{String(label)}</button>
      ))}
    </div>
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
