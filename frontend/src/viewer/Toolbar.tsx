import { useState } from 'react';

interface ToolbarProps {
  pointSize: number;
  onPointSizeChange: (v: number) => void;
  pointCount: number;
  originalCount: number;
  onVoxelDownsample: (voxelSize: number) => void;
  onReset: () => void;
  measurementMode: boolean;
  onToggleMeasure: () => void;
  distance: number | null;
  onClearMeasure: () => void;
  onResetView: () => void;
}

export default function Toolbar({
  pointSize, onPointSizeChange, pointCount, originalCount,
  onVoxelDownsample, onReset, measurementMode, onToggleMeasure,
  distance, onClearMeasure, onResetView,
}: ToolbarProps) {
  const [voxelSize, setVoxelSize] = useState(0.02);

  return (
    <div className="absolute top-3 right-3 z-10 bg-gray-900/90 backdrop-blur rounded-lg p-3 text-xs space-y-3 w-52 select-none">
      <div className="flex items-center justify-between">
        <span className="text-gray-400 font-medium">工具</span>
        <span className="text-gray-600">
          {(pointCount / 10000).toFixed(0)}万点
          {pointCount !== originalCount && ` / 原${(originalCount / 10000).toFixed(0)}万`}
        </span>
      </div>

      {/* Point Size */}
      <div>
        <label className="text-gray-500">点大小</label>
        <input type="range" min={0.002} max={0.03} step={0.001} value={pointSize}
          onChange={(e) => onPointSizeChange(Number(e.target.value))}
          className="w-full mt-1 accent-blue-500" />
      </div>

      {/* Voxel Downsample */}
      <div>
        <label className="text-gray-500">体素降采样 (m)</label>
        <div className="flex gap-1 mt-1">
          <input type="number" min={0.005} max={0.5} step={0.005} value={voxelSize}
            onChange={(e) => setVoxelSize(Number(e.target.value))}
            className="w-16 bg-gray-800 rounded px-1.5 py-1 text-white text-xs border border-gray-700" />
          <button onClick={() => onVoxelDownsample(voxelSize)}
            className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded px-2 py-1 transition-colors">
            降采样
          </button>
          <button onClick={onReset}
            className="bg-gray-800 hover:bg-gray-700 text-gray-400 rounded px-2 py-1 transition-colors">
            重置
          </button>
        </div>
      </div>

      {/* Measure */}
      <div>
        <button onClick={onToggleMeasure}
          className={`w-full rounded px-2 py-1.5 transition-colors ${measurementMode ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 'bg-gray-800 hover:bg-gray-700 text-gray-400'}`}>
          {measurementMode ? '测量中 (点击两点)' : '距离测量'}
        </button>
        {distance !== null && (
          <div className="flex justify-between items-center mt-1 px-1">
            <span className="text-yellow-400">{(distance * 100).toFixed(1)} cm</span>
            <button onClick={onClearMeasure} className="text-gray-600 hover:text-gray-400">✕</button>
          </div>
        )}
      </div>

      {/* Reset View */}
      <button onClick={onResetView}
        className="w-full bg-gray-800 hover:bg-gray-700 text-gray-400 rounded px-2 py-1 transition-colors">
        复位视图
      </button>
    </div>
  );
}
