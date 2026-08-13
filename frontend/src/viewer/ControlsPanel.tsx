import { useEffect, useState } from 'react';
import * as THREE from 'three';
import type { BoxClip } from './Toolbar';
import type { RenderPresetName, ViewerRenderSettings } from './renderSettings';

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
  exposure: number; setExposure: (v: number) => void;
  viewMode: string;
  edgeThreshold: number; setEdgeThreshold: (v: number) => void;
  onScreenshot: () => void;
  onResetView: () => void;
  showGrid: boolean; setShowGrid: (v: boolean) => void;
  bloomStrength: number; setBloomStrength: (v: number) => void;
  orientMode?: boolean; setOrientMode?: (v: boolean) => void;
  orientMarkers?: THREE.Vector3[] | null;
  orientPlane?: { normal: THREE.Vector3; center: THREE.Vector3 } | null;
  onApplyOrient?: () => void;
  onCancelOrient?: () => void;
  lassoEnabled?: boolean; setLassoEnabled?: (v: boolean) => void;
  selectedCount?: number;
  annotations?: any[]; onClearAnnotations?: () => void;
  renderSettings: ViewerRenderSettings;
  updateRenderSetting: <K extends keyof ViewerRenderSettings>(key: K, value: ViewerRenderSettings[K]) => void;
  applyRenderPreset: (name: RenderPresetName) => void;
  resetRenderSettings: () => void;
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
      </div>

      {/* Right-side circular controls */}
      <div className="absolute right-3 top-1/2 -translate-y-1/2 z-10 flex flex-col gap-2">
        {/* View / Display */}
        <Btn icon="⊙" label="显示设置" active={panel === 'view'} onClick={() => toggle('view')} />
        {panel === 'view' && <ViewPanel {...p} />}

        {/* Color Mode */}
        <Btn icon="◉" label="着色模式" active={panel === 'color'} onClick={() => toggle('color')} />
        {panel === 'color' && <ColorPanel colorMode={p.colorMode} setColorMode={p.setColorMode}
          exposure={p.exposure} setExposure={p.setExposure} viewMode={p.viewMode} />}

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

/* ── View Panel ─────────────────────────────────────── */
function ViewPanel(p: CtrlProps) {
  const settings = p.renderSettings;
  const update = p.updateRenderSetting;
  const [advanced, setAdvanced] = useState(false);
  const [edgeDraft, setEdgeDraft] = useState(settings.edgeThreshold);

  useEffect(() => setEdgeDraft(settings.edgeThreshold), [settings.edgeThreshold]);
  const commitEdgeThreshold = () => update('edgeThreshold', edgeDraft);
  const isPointMode = p.viewMode === 'points';
  const isGaussianMode = p.viewMode === 'gaussian';
  const isSurfaceMode = p.viewMode === 'mesh';
  const isWireframeMode = p.viewMode === 'wireframe';

  return (
    <Card title="渲染设置">
      <Section title="预设">
        <div className="grid grid-cols-3 gap-1">
          {([
            ['natural', '自然'],
            ['bright', '明亮'],
            ['dark', '暗场'],
            ['detail', '细节'],
            ['performance', '性能'],
          ] as [RenderPresetName, string][]).map(([name, label]) => (
            <button key={name} onClick={() => p.applyRenderPreset(name)}
              className="rounded bg-gray-800/60 px-1 py-1 text-[10px] text-gray-400 hover:bg-blue-500/20 hover:text-blue-300">
              {label}
            </button>
          ))}
          <button onClick={p.resetRenderSettings}
            className="rounded bg-gray-800/60 px-1 py-1 text-[10px] text-gray-400 hover:bg-gray-700 hover:text-white">
            恢复默认
          </button>
        </div>
      </Section>

      <Section title="通用 · 立即生效">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-gray-500">背景色</span>
          <input aria-label="背景色" type="color" value={settings.backgroundColor}
            onChange={e => update('backgroundColor', e.target.value)}
            className="h-6 w-10 cursor-pointer rounded border border-gray-700 bg-transparent" />
        </div>
        <Range label="曝光" value={settings.exposure} min={0.4} max={2} step={0.05}
          onChange={value => update('exposure', value)} />
        <Range label="视野 FOV" value={settings.fov} min={30} max={90} step={1} suffix="°"
          onChange={value => update('fov', value)} />
        <Range label="灯光总倍率" value={settings.lightIntensity} min={0.25} max={2} step={0.05}
          onChange={value => update('lightIntensity', value)} />
        <Range label="辉光" value={settings.bloomStrength} min={0} max={0.5} step={0.01}
          onChange={value => update('bloomStrength', value)} />
      </Section>

      {isPointMode && (
        <Section title="点云 · 立即生效">
          <Range label="点大小" value={settings.pointSize} min={0.001} max={0.05} step={0.001} digits={4}
            onChange={value => update('pointSize', value)} />
          <Range label="透明度" value={settings.pointOpacity} min={0.1} max={1} step={0.05}
            onChange={value => update('pointOpacity', value)} />
          <Choice label="点形状" value={settings.pointShape}
            options={[['square', '方点'], ['circle', '圆点']]}
            onChange={value => update('pointShape', value as ViewerRenderSettings['pointShape'])} />
          <Toggle label="深度遮挡" value={settings.pointDepthTest}
            onChange={value => update('pointDepthTest', value)} />
        </Section>
      )}

      {isGaussianMode && (
        <Section title="高斯软点 · 立即生效">
          <p className="mb-2 text-[9px] leading-4 text-amber-400/80">点云高斯软点显示，不含真实 3DGS 协方差与球谐参数。</p>
          <Range label="基础点大小" value={settings.pointSize} min={0.001} max={0.05} step={0.001} digits={4}
            onChange={value => update('pointSize', value)} />
          <Range label="半径倍率" value={settings.gaussianRadius} min={1} max={8} step={0.25} suffix="×"
            onChange={value => update('gaussianRadius', value)} />
          <Range label="有效透明度" value={settings.gaussianOpacity} min={0.1} max={0.9} step={0.05}
            onChange={value => update('gaussianOpacity', value)} />
          <Range label="高斯衰减" value={settings.gaussianFalloff} min={0.5} max={4} step={0.1}
            onChange={value => update('gaussianFalloff', value)} />
          <Range label="边缘裁切" value={settings.gaussianEdgeCutoff} min={0} max={0.1} step={0.005} digits={3}
            onChange={value => update('gaussianEdgeCutoff', value)} />
          <Choice label="混合模式" value={settings.gaussianBlend}
            options={[['normal', '自然'], ['additive', '发光']]}
            onChange={value => update('gaussianBlend', value as ViewerRenderSettings['gaussianBlend'])} />
          {settings.gaussianBlend === 'additive' && (
            <p className="mb-2 text-[9px] text-amber-400/80">发光模式自动将有效透明度限制为 0.35，避免过曝。</p>
          )}
          <Toggle label="深度写入" value={settings.gaussianDepthWrite}
            onChange={value => update('gaussianDepthWrite', value)} />
        </Section>
      )}

      {(isSurfaceMode || isWireframeMode) && (
        <Section title={isWireframeMode ? '表面衬底 · 立即生效' : '表面 · 立即生效'}>
          <Range label="粗糙度" value={settings.surfaceRoughness} min={0.2} max={1} step={0.02}
            onChange={value => update('surfaceRoughness', value)} />
          <Range label="金属度" value={settings.surfaceMetalness} min={0} max={0.4} step={0.02}
            onChange={value => update('surfaceMetalness', value)} />
          <Range label="表面亮度" value={settings.surfaceColorBrightness} min={0.5} max={1.5} step={0.05}
            onChange={value => update('surfaceColorBrightness', value)} />
          <Choice label="着色法线" value={settings.surfaceFlatShading ? 'flat' : 'smooth'}
            options={[['smooth', '平滑'], ['flat', '平面']]}
            onChange={value => update('surfaceFlatShading', value === 'flat')} />
          <Toggle label="双面显示" value={settings.surfaceDoubleSide}
            onChange={value => update('surfaceDoubleSide', value)} />
        </Section>
      )}

      {isWireframeMode && (
        <Section title="结构线 · 松手应用">
          <Range label="折痕阈值" value={edgeDraft} min={1} max={80} step={1} suffix="°"
            onChange={setEdgeDraft} onCommit={commitEdgeThreshold} />
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-gray-500">线条颜色</span>
            <input aria-label="结构线颜色" type="color" value={settings.edgeColor}
              onChange={e => update('edgeColor', e.target.value)}
              className="h-6 w-10 cursor-pointer rounded border border-gray-700 bg-transparent" />
          </div>
          <Range label="线条透明度" value={settings.edgeOpacity} min={0.1} max={1} step={0.05}
            onChange={value => update('edgeOpacity', value)} />
        </Section>
      )}

      <button onClick={() => setAdvanced(value => !value)}
        className="mb-2 text-[10px] text-gray-500 hover:text-gray-300">
        {advanced ? '收起高级设置' : '展开高级设置'}
      </button>
      {advanced && (
        <Section title="高级灯光与辉光">
          <Range label="环境光" value={settings.ambientLight} min={0} max={3} step={0.05}
            onChange={value => update('ambientLight', value)} />
          <Range label="主光 Key" value={settings.keyLight} min={0} max={3} step={0.05}
            onChange={value => update('keyLight', value)} />
          <Range label="补光 Fill" value={settings.fillLight} min={0} max={3} step={0.05}
            onChange={value => update('fillLight', value)} />
          <Range label="轮廓光 Rim" value={settings.rimLight} min={0} max={3} step={0.05}
            onChange={value => update('rimLight', value)} />
          <Range label="辉光阈值" value={settings.bloomThreshold} min={0.5} max={1} step={0.01}
            onChange={value => update('bloomThreshold', value)} />
          <Range label="辉光平滑" value={settings.bloomSmoothing} min={0} max={0.5} step={0.01}
            onChange={value => update('bloomSmoothing', value)} />
        </Section>
      )}

      <div className="grid grid-cols-3 gap-1 mb-2">
        <ToggleButton label="坐标轴" value={settings.showAxes} onClick={() => update('showAxes', !settings.showAxes)} />
        <ToggleButton label="网格" value={settings.showGrid} onClick={() => update('showGrid', !settings.showGrid)} />
        <ToggleButton label="轨迹" value={settings.showTrajectory} onClick={() => update('showTrajectory', !settings.showTrajectory)} />
      </div>
      <button onClick={p.onResetView}
        className="w-full rounded bg-gray-800/60 py-1 text-[10px] text-gray-400 hover:bg-gray-700 hover:text-white">
        复位视图
      </button>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 border-b border-gray-800/80 pb-3 last:border-b-0">
      <div className="mb-2 text-[10px] font-medium text-gray-400">{title}</div>
      {children}
    </div>
  );
}

function Range({ label, value, min, max, step, digits = 2, suffix = '', onChange, onCommit }: {
  label: string; value: number; min: number; max: number; step: number; digits?: number; suffix?: string;
  onChange: (value: number) => void; onCommit?: () => void;
}) {
  return (
    <label className="mb-2 block text-gray-500">
      <span className="mb-1 flex justify-between">
        <span>{label}</span><span className="font-mono text-gray-600">{value.toFixed(digits)}{suffix}</span>
      </span>
      <input aria-label={label} type="range" min={min} max={max} step={step} value={value}
        onChange={event => onChange(Number(event.target.value))}
        onPointerUp={onCommit} onKeyUp={onCommit} onBlur={onCommit}
        className="w-full accent-blue-500" />
    </label>
  );
}

function Choice({ label, value, options, onChange }: {
  label: string; value: string; options: [string, string][]; onChange: (value: string) => void;
}) {
  return (
    <div className="mb-2">
      <div className="mb-1 text-gray-500">{label}</div>
      <div className="grid grid-cols-2 gap-1">
        {options.map(([key, text]) => (
          <button key={key} onClick={() => onChange(key)}
            className={`rounded py-1 text-[10px] ${value === key ? 'border border-blue-500/30 bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="mb-2 flex items-center justify-between text-gray-500">
      <span>{label}</span>
      <button onClick={() => onChange(!value)} role="switch" aria-checked={value}
        className={`h-5 w-9 rounded-full p-0.5 transition-colors ${value ? 'bg-blue-500' : 'bg-gray-700'}`}>
        <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${value ? 'translate-x-4' : ''}`} />
      </button>
    </label>
  );
}

function ToggleButton({ label, value, onClick }: { label: string; value: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`rounded py-1 text-[10px] ${value ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800/50 text-gray-500'}`}>
      {label}
    </button>
  );
}

/* ── Color Panel (gaussian toggle removed) ─────────── */
function ColorPanel({ colorMode, setColorMode, exposure, setExposure, viewMode }: any) {
  const showPointColors = viewMode === 'points' || viewMode === 'gaussian';
  return (
    <Card title="着色与曝光">
      {showPointColors && <div className="grid grid-cols-2 gap-1 mb-3">
        {[
          ['rgb', '原始色'],
          ['height', '高度'],
          ['depth', '深度'],
          ['white', '白色'],
        ].map(([k, label]) => (
          <button key={k} onClick={() => setColorMode(k)}
            className={`py-1 rounded text-[10px] ${colorMode === k ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'bg-gray-800/50 text-gray-500'}`}>
            {label}
          </button>
        ))}
      </div>}

      <label className="text-gray-500 block mb-1">曝光 <span className="text-gray-600">{exposure.toFixed(1)}</span></label>
      <input type="range" min={0.6} max={1.4} step={0.05} value={exposure}
        onChange={e => setExposure(Number(e.target.value))} className="w-full accent-blue-500" />
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

/* ── Card wrapper ─────────────────────────────────── */
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="absolute right-12 top-0 bg-gray-900/95 backdrop-blur rounded-xl p-3 w-72 text-[11px] border border-gray-800 shadow-2xl max-h-[78vh] overflow-y-auto">
      <div className="text-gray-300 font-semibold mb-2 text-xs border-b border-gray-800 pb-1.5">{title}</div>
      {children}
    </div>
  );
}
