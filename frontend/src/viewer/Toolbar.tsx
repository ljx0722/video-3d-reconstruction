import { useState } from 'react';

export interface ClipPlane {
  axis: 'x' | 'y' | 'z';
  offset: number;
  enabled: boolean;
  negative: boolean; // true = clip negative side, false = clip positive side
}

export interface BoxClip {
  enabled: boolean;
  min: [number, number, number];
  max: [number, number, number];
}

interface ToolbarProps {
  pointSize: number;
  onPointSizeChange: (v: number) => void;
  opacity: number;
  onOpacityChange: (v: number) => void;
  pointCount: number;
  originalCount: number;
  onVoxelDownsample: (voxelSize: number) => void;
  onOutlierRemove: (k: number, std: number) => void;
  onReset: () => void;
  measurementMode: boolean;
  onToggleMeasure: () => void;
  distance: number | null;
  onClearMeasure: () => void;
  onResetView: () => void;
  clipPlanes: ClipPlane[];
  onClipPlanesChange: (planes: ClipPlane[]) => void;
  boxClip: BoxClip;
  onBoxClipChange: (bc: BoxClip) => void;
  onExport: (format: string) => void;
  showAxes: boolean;
  onToggleAxes: () => void;
  bgColor: 'dark' | 'light';
  onBgColorChange: (c: 'dark' | 'light') => void;
}

export default function Toolbar({
  pointSize, onPointSizeChange, opacity, onOpacityChange,
  pointCount, originalCount, onVoxelDownsample, onOutlierRemove, onReset,
  measurementMode, onToggleMeasure, distance, onClearMeasure, onResetView,
  clipPlanes, onClipPlanesChange, boxClip, onBoxClipChange, onExport,
  showAxes, onToggleAxes, bgColor, onBgColorChange,
}: ToolbarProps) {
  const [voxelSize, setVoxelSize] = useState(0.02);
  const [outlierK, setOutlierK] = useState(6);
  const [outlierStd, setOutlierStd] = useState(1.0);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    vis: true, process: true, clip: false, measure: false, export: false,
  });

  const toggle = (k: string) => setExpanded(s => ({ ...s, [k]: !s[k] }));

  const updatePlane = (i: number, up: Partial<ClipPlane>) => {
    const next = clipPlanes.map((p, j) => j === i ? { ...p, ...up } : p);
    onClipPlanesChange(next);
  };

  return (
    <div className="absolute top-3 right-3 z-10 bg-gray-900/90 backdrop-blur rounded-lg p-2 text-[11px] w-56 select-none font-sans space-y-1 max-h-[calc(100vh-200px)] overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-1 mb-2">
        <span className="text-gray-300 font-semibold text-xs">点云工具</span>
        <span className="text-gray-600 text-[10px]">
          {(pointCount / 10000).toFixed(1)}万
          {pointCount !== originalCount && ` · ${(pointCount / originalCount * 100).toFixed(0)}%`}
        </span>
      </div>

      {/* Visualization */}
      <Section title="可视化" expanded={expanded.vis} onToggle={() => toggle('vis')}>
        {/* Point Size */}
        <label className="text-gray-500 block mb-1">点大小 <span className="text-gray-700">{pointSize.toFixed(3)}</span></label>
        <input type="range" min={0.002} max={0.04} step={0.001} value={pointSize}
          onChange={e => onPointSizeChange(Number(e.target.value))} className="w-full accent-blue-500 mb-2" />

        {/* Opacity */}
        <label className="text-gray-500 block mb-1">透明度 <span className="text-gray-700">{opacity.toFixed(2)}</span></label>
        <input type="range" min={0.1} max={1} step={0.05} value={opacity}
          onChange={e => onOpacityChange(Number(e.target.value))} className="w-full accent-blue-500 mb-2" />

        {/* BG Color */}
        <div className="flex gap-1 mt-1">
          <button onClick={() => onBgColorChange('dark')}
            className={`flex-1 py-1 rounded text-[10px] ${bgColor === 'dark' ? 'bg-blue-500/30 text-blue-400' : 'bg-gray-800 text-gray-500'}`}>暗色</button>
          <button onClick={() => onBgColorChange('light')}
            className={`flex-1 py-1 rounded text-[10px] ${bgColor === 'light' ? 'bg-blue-500/30 text-blue-400' : 'bg-gray-800 text-gray-500'}`}>亮色</button>
          <button onClick={onToggleAxes}
            className={`flex-1 py-1 rounded text-[10px] ${showAxes ? 'bg-blue-500/30 text-blue-400' : 'bg-gray-800 text-gray-500'}`}>坐标轴</button>
        </div>
      </Section>

      {/* Processing */}
      <Section title="处理" expanded={expanded.process} onToggle={() => toggle('process')}>
        {/* Voxel Downsample */}
        <label className="text-gray-500 block mb-1">体素降采样</label>
        <div className="flex gap-1 mb-2">
          <input type="number" min={0.005} max={0.5} step={0.005} value={voxelSize}
            onChange={e => setVoxelSize(Number(e.target.value))}
            className="w-14 bg-gray-800 rounded px-1.5 py-1 text-white border border-gray-700" />
          <button onClick={() => onVoxelDownsample(voxelSize)}
            className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-0.5 transition-colors">执行</button>
        </div>

        {/* Outlier Removal */}
        <label className="text-gray-500 block mb-1">统计滤波去噪</label>
        <div className="flex gap-1 mb-2">
          <input type="number" min={2} max={50} value={outlierK}
            onChange={e => setOutlierK(Number(e.target.value))}
            className="w-10 bg-gray-800 rounded px-1 py-1 text-white border border-gray-700" title="近邻数K" />
          <input type="number" min={0.1} max={5} step={0.1} value={outlierStd}
            onChange={e => setOutlierStd(Number(e.target.value))}
            className="w-12 bg-gray-800 rounded px-1 py-1 text-white border border-gray-700" title="标准差倍数" />
          <button onClick={() => onOutlierRemove(outlierK, outlierStd)}
            className="flex-1 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded px-2 py-0.5 transition-colors">去噪</button>
        </div>

        <button onClick={onReset}
          className="w-full bg-gray-800 hover:bg-gray-700 text-gray-400 rounded px-2 py-1 transition-colors">恢复原始点云</button>
      </Section>

      {/* Clipping */}
      <Section title="裁剪" expanded={expanded.clip} onToggle={() => toggle('clip')}>
        {/* Plane Clipping */}
        <div className="text-gray-500 mb-1">平面裁剪</div>
        {clipPlanes.map((p, i) => (
          <div key={p.axis} className={`mb-1.5 p-1.5 rounded ${p.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/50'}`}>
            <div className="flex items-center gap-1 mb-0.5">
              <button onClick={() => updatePlane(i, { enabled: !p.enabled })}
                className={`w-4 h-4 rounded text-[9px] flex items-center justify-center ${p.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-500'}`}>
                {p.enabled ? '✓' : ''}</button>
              <span className="text-gray-400 uppercase w-3">{p.axis}</span>
              <span className={`text-[9px] ${p.negative ? 'text-red-400' : 'text-green-400'}`}>
                {p.negative ? '-∞..' : '..+∞'}
              </span>
              <button onClick={() => updatePlane(i, { negative: !p.negative })}
                className="text-[9px] bg-gray-700 hover:bg-gray-600 px-1 rounded text-gray-400">翻转</button>
            </div>
            <input type="range" min={-3} max={3} step={0.01} value={p.offset}
              onChange={e => updatePlane(i, { offset: Number(e.target.value) })}
              className="w-full accent-green-500 h-1" />
            <div className="text-[9px] text-gray-600 text-right">{p.offset.toFixed(2)}m</div>
          </div>
        ))}

        {/* Box Clipping */}
        <div className="text-gray-500 mb-1 mt-2">包围盒裁剪</div>
        <div className={`p-1.5 rounded mb-1 ${boxClip.enabled ? 'bg-green-500/10 border border-green-500/20' : 'bg-gray-800/50'}`}>
          <label className="flex items-center gap-1 mb-1">
            <button onClick={() => onBoxClipChange({ ...boxClip, enabled: !boxClip.enabled })}
              className={`w-4 h-4 rounded text-[9px] flex items-center justify-center ${boxClip.enabled ? 'bg-green-500 text-white' : 'bg-gray-700 text-gray-500'}`}>
              {boxClip.enabled ? '✓' : ''}</button>
            <span className="text-gray-400">启用</span>
          </label>
          {boxClip.enabled && (
            <div className="grid grid-cols-2 gap-1 text-[9px]">
              {['min', 'max'].map(mode => ['x', 'y', 'z'].map(axis => {
                const idx = { x: 0, y: 1, z: 2 }[axis as 'x' | 'y' | 'z'];
                const val = boxClip[mode as 'min' | 'max'][idx];
                return (
                  <div key={`${mode}-${axis}`} className="flex items-center gap-0.5">
                    <span className="text-gray-600 w-4">{mode}{axis}</span>
                    <input type="number" min={-10} max={10} step={0.01} value={val}
                      onChange={e => {
                        const arr = [...boxClip[mode as 'min' | 'max']] as [number, number, number];
                        arr[idx] = Number(e.target.value);
                        onBoxClipChange({ ...boxClip, [mode]: arr });
                      }}
                      className="flex-1 bg-gray-800 rounded px-1 py-0.5 text-white border border-gray-700 w-12" />
                  </div>
                );
              }))}
            </div>
          )}
        </div>
      </Section>

      {/* Measure */}
      <Section title="测量" expanded={expanded.measure} onToggle={() => toggle('measure')}>
        <button onClick={onToggleMeasure}
          className={`w-full rounded px-2 py-1 transition-colors text-[11px] ${measurementMode ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 'bg-gray-800 hover:bg-gray-700 text-gray-400'}`}>
          {measurementMode ? '测量中 (点选两点)' : '距离测量'}
        </button>
        {distance !== null && (
          <div className="flex justify-between items-center mt-1 px-1">
            <span className="text-yellow-400 text-[10px]">{(distance * 100).toFixed(1)} cm</span>
            <button onClick={onClearMeasure} className="text-gray-600 hover:text-gray-400">✕</button>
          </div>
        )}
      </Section>

      {/* Export */}
      <Section title="导出" expanded={expanded.export} onToggle={() => toggle('export')}>
        <div className="flex gap-1">
          {['PLY', 'XYZ', 'GLB'].map(fmt => (
            <button key={fmt} onClick={() => onExport(fmt)}
              className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded px-2 py-1 transition-colors text-[10px]">
              .{fmt.toLowerCase()}
            </button>
          ))}
        </div>
      </Section>

      {/* Quick Actions */}
      <button onClick={onResetView}
        className="w-full bg-gray-800 hover:bg-gray-700 text-gray-500 rounded px-2 py-1 transition-colors text-[10px]">
        复位视图
      </button>
    </div>
  );
}

function Section({ title, expanded, onToggle, children }: {
  title: string; expanded: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  return (
    <div className="border-t border-gray-800 pt-1">
      <button onClick={onToggle}
        className="w-full flex items-center justify-between py-1 text-gray-400 hover:text-gray-200 transition-colors">
        <span className="text-[11px] font-medium">{title}</span>
        <span className="text-[9px] text-gray-600">{expanded ? '▼' : '▶'}</span>
      </button>
      {expanded && <div className="pb-1">{children}</div>}
    </div>
  );
}
