import { useCallback, useEffect, useRef, useState } from 'react';
import type { Sam2Prompt } from '../types';

export interface VideoMetadata {
  source_fps: number;
  source_frame_count: number;
  source_width: number;
  source_height: number;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function mapDisplayedToSource(
  clientX: number,
  clientY: number,
  rect: Rect,
  sourceWidth: number,
  sourceHeight: number,
): { x: number; y: number } | null {
  if (rect.width <= 0 || rect.height <= 0 || sourceWidth <= 0 || sourceHeight <= 0) return null;
  const scale = Math.min(rect.width / sourceWidth, rect.height / sourceHeight);
  const contentWidth = sourceWidth * scale;
  const contentHeight = sourceHeight * scale;
  const offsetX = (rect.width - contentWidth) / 2;
  const offsetY = (rect.height - contentHeight) / 2;
  const x = (clientX - rect.left - offsetX) / scale;
  const y = (clientY - rect.top - offsetY) / scale;
  if (x < 0 || y < 0 || x > sourceWidth || y > sourceHeight) return null;
  return { x, y };
}

export function sourceToDisplayed(
  x: number,
  y: number,
  rect: Rect,
  sourceWidth: number,
  sourceHeight: number,
): { x: number; y: number } {
  const scale = Math.min(rect.width / sourceWidth, rect.height / sourceHeight);
  const contentWidth = sourceWidth * scale;
  const contentHeight = sourceHeight * scale;
  return {
    x: rect.left + (rect.width - contentWidth) / 2 + x * scale,
    y: rect.top + (rect.height - contentHeight) / 2 + y * scale,
  };
}

type Tool = 'point-keep' | 'point-exclude' | 'box-keep' | 'box-exclude';

export default function Sam2PromptPanel({
  videoUrl,
  metadata,
  onCancel,
  onSubmit,
}: {
  videoUrl: string;
  metadata: VideoMetadata;
  onCancel: () => void;
  onSubmit: (prompts: Sam2Prompt[]) => void;
}) {
  const [tool, setTool] = useState<Tool>('point-keep');
  const [prompts, setPrompts] = useState<Sam2Prompt[]>([]);
  const [draftBox, setDraftBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const boxStartRef = useRef<{ x: number; y: number } | null>(null);
  const submitDisabled = prompts.length === 0;

  const frameIndexOfVideo = useCallback(() => {
    const video = videoRef.current;
    if (!video) return 0;
    return Math.max(0, Math.min(metadata.source_frame_count - 1, Math.floor(video.currentTime * metadata.source_fps)));
  }, [metadata]);

  const drawOverlay = useCallback(() => {
    const canvas = overlayRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;
    const rect = video.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const drawPrompt = (prompt: Sam2Prompt) => {
      const isExclude = prompt.operation === 'exclude';
      ctx.strokeStyle = isExclude ? '#f87171' : '#22d3ee';
      ctx.fillStyle = isExclude ? '#f87171' : '#22d3ee';
      ctx.lineWidth = 2;
      if (prompt.kind === 'point') {
        const p = sourceToDisplayed(prompt.x, prompt.y, rect, metadata.source_width, metadata.source_height);
        ctx.beginPath();
        ctx.arc(p.x - rect.left, p.y - rect.top, 6, 0, Math.PI * 2);
        ctx.fill();
        if (prompt.label === 0) {
          ctx.strokeStyle = '#fff';
          ctx.beginPath();
          ctx.moveTo(p.x - rect.left - 3, p.y - rect.top - 3);
          ctx.lineTo(p.x - rect.left + 3, p.y - rect.top + 3);
          ctx.moveTo(p.x - rect.left + 3, p.y - rect.top - 3);
          ctx.lineTo(p.x - rect.left - 3, p.y - rect.top + 3);
          ctx.stroke();
        }
      } else {
        const a = sourceToDisplayed(prompt.x0, prompt.y0, rect, metadata.source_width, metadata.source_height);
        const b = sourceToDisplayed(prompt.x1, prompt.y1, rect, metadata.source_width, metadata.source_height);
        ctx.strokeRect(a.x - rect.left, a.y - rect.top, b.x - a.x, b.y - a.y);
      }
    };

    prompts.forEach(drawPrompt);
    if (draftBox) {
      const a = sourceToDisplayed(draftBox.x0, draftBox.y0, rect, metadata.source_width, metadata.source_height);
      const b = sourceToDisplayed(draftBox.x1, draftBox.y1, rect, metadata.source_width, metadata.source_height);
      ctx.strokeStyle = tool.endsWith('exclude') ? '#f87171' : '#22d3ee';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(a.x - rect.left, a.y - rect.top, b.x - a.x, b.y - a.y);
      ctx.setLineDash([]);
    }
  }, [prompts, draftBox, metadata, tool]);

  useEffect(() => {
    drawOverlay();
  }, [drawOverlay]);

  useEffect(() => {
    const resize = () => drawOverlay();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, [drawOverlay]);

  const addPoint = useCallback((clientX: number, clientY: number) => {
    const video = videoRef.current;
    if (!video) return;
    const rect = video.getBoundingClientRect();
    const mapped = mapDisplayedToSource(clientX, clientY, rect, metadata.source_width, metadata.source_height);
    if (!mapped) return;
    video.pause();
    const frame = frameIndexOfVideo();
    const operation = tool.endsWith('exclude') ? 'exclude' : 'keep';
    const objectId = operation === 'keep' ? 1 : 2;
    const label = 1;
    const prompt: Sam2Prompt = {
      kind: 'point',
      frame_index: frame,
      x: Math.round(mapped.x * 100) / 100,
      y: Math.round(mapped.y * 100) / 100,
      label,
      object_id: objectId,
      operation,
    };
    setPrompts(prev => [...prev, prompt]);
  }, [tool, metadata, frameIndexOfVideo]);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const video = videoRef.current;
    if (!video) return;
    const rect = video.getBoundingClientRect();
    const mapped = mapDisplayedToSource(e.clientX, e.clientY, rect, metadata.source_width, metadata.source_height);
    if (!mapped) return;
    if (tool.startsWith('box')) {
      video.pause();
      boxStartRef.current = { x: mapped.x, y: mapped.y };
      setDraftBox({ x0: mapped.x, y0: mapped.y, x1: mapped.x, y1: mapped.y });
    } else {
      addPoint(e.clientX, e.clientY);
    }
  }, [tool, metadata, addPoint]);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!boxStartRef.current) return;
    const video = videoRef.current;
    if (!video) return;
    const rect = video.getBoundingClientRect();
    const mapped = mapDisplayedToSource(e.clientX, e.clientY, rect, metadata.source_width, metadata.source_height);
    if (!mapped) return;
    const start = boxStartRef.current;
    setDraftBox({
      x0: Math.min(start.x, mapped.x),
      y0: Math.min(start.y, mapped.y),
      x1: Math.max(start.x, mapped.x),
      y1: Math.max(start.y, mapped.y),
    });
  }, [metadata]);

  const onPointerUp = useCallback(() => {
    if (!boxStartRef.current || !draftBox) return;
    boxStartRef.current = null;
    const operation = tool.endsWith('exclude') ? 'exclude' : 'keep';
    const objectId = operation === 'keep' ? 1 : 2;
    if (draftBox.x1 - draftBox.x0 > 2 && draftBox.y1 - draftBox.y0 > 2) {
      const prompt: Sam2Prompt = {
        kind: 'box',
        frame_index: frameIndexOfVideo(),
        x0: Math.round(draftBox.x0 * 100) / 100,
        y0: Math.round(draftBox.y0 * 100) / 100,
        x1: Math.round(draftBox.x1 * 100) / 100,
        y1: Math.round(draftBox.y1 * 100) / 100,
        object_id: objectId,
        operation,
      };
      setPrompts(prev => [...prev, prompt]);
    }
    setDraftBox(null);
  }, [tool, draftBox, frameIndexOfVideo]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onTime = () => {
      setFrameIndex(frameIndexOfVideo());
      drawOverlay();
    };
    video.addEventListener('timeupdate', onTime);
    video.addEventListener('seeked', onTime);
    return () => {
      video.removeEventListener('timeupdate', onTime);
      video.removeEventListener('seeked', onTime);
    };
  }, [frameIndexOfVideo, drawOverlay]);

  const removePrompt = (index: number) => setPrompts(prev => prev.filter((_, i) => i !== index));

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }, []);

  const seekToFrame = useCallback((frame: number) => {
    const video = videoRef.current;
    if (!video) return;
    const clamped = Math.max(0, Math.min(metadata.source_frame_count - 1, Math.floor(frame)));
    video.pause();
    video.currentTime = clamped / metadata.source_fps;
    setFrameIndex(clamped);
  }, [metadata]);

  const tools: [Tool, string][] = [
    ['point-keep', '保留点'],
    ['point-exclude', '排除点'],
    ['box-keep', '保留框'],
    ['box-exclude', '排除框'],
  ];

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex max-h-full w-full max-w-5xl flex-col gap-3 rounded-xl border border-gray-800 bg-gray-950/95 p-4 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-200">高质量表面 · SAM2 区域标记</div>
          <button onClick={onCancel} className="rounded px-2 py-1 text-xs text-gray-500 hover:text-white">关闭</button>
        </div>
        <p className="text-[11px] leading-4 text-gray-500">
          暂停视频，用「保留点/保留框」框选要重建的对象，用「排除点/排除框」去除动态区域。提示会随任务进入 GPU 预训练 SAM2，传播到所有重建帧后清理深度与置信度。
        </p>
        <div className="flex items-center gap-1">
          {tools.map(([value, label]) => (
            <button key={value} onClick={() => setTool(value)}
              className={`rounded px-2.5 py-1 text-[11px] ${tool === value
                ? value.endsWith('exclude') ? 'bg-red-500/20 text-red-300' : 'bg-blue-500/20 text-blue-300'
                : 'bg-gray-800/60 text-gray-400 hover:text-white'}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="relative w-full overflow-hidden rounded-lg bg-black">
          <video ref={videoRef} src={videoUrl} className="w-full" preload="auto"
            onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
          <canvas ref={overlayRef} className="pointer-events-auto absolute inset-0 h-full w-full cursor-crosshair"
            onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} />
        </div>
        <div className="flex items-center gap-2">
          <button onClick={togglePlay}
            className="rounded bg-gray-800 px-2.5 py-1 text-[11px] text-gray-200 hover:bg-gray-700">
            {playing ? '暂停' : '播放'}
          </button>
          <input
            type="range"
            min={0}
            max={metadata.source_frame_count - 1}
            value={frameIndex}
            onChange={e => seekToFrame(Number(e.target.value))}
            className="flex-1 accent-blue-500"
          />
          <span className="w-28 text-right text-[10px] tabular-nums text-gray-500">
            帧 {frameIndex + 1} / {metadata.source_frame_count}
          </span>
        </div>
        <div className="max-h-32 overflow-y-auto text-[11px]">
          {prompts.length === 0 && <div className="py-2 text-center text-gray-600">尚未添加标记</div>}
          {prompts.map((prompt, index) => (
            <div key={index} className="flex items-center justify-between rounded px-2 py-1 odd:bg-gray-900/60">
              <span className="text-gray-300">
                {prompt.operation === 'keep' ? '保留' : '排除'} · {prompt.kind === 'point' ? '点' : '框'} · 帧 {prompt.frame_index + 1}
                {prompt.kind === 'point' ? ` (${prompt.x}, ${prompt.y})` : ` [${prompt.x0},${prompt.y0}–${prompt.x1},${prompt.y1}]`}
              </span>
              <button onClick={() => removePrompt(index)} className="text-red-400 hover:text-red-300">删除</button>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">取消</button>
          <button disabled={submitDisabled}
            onClick={() => onSubmit(prompts)}
            className="rounded bg-blue-500 px-3 py-1.5 text-xs text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40">
            开始高质量重建
          </button>
        </div>
      </div>
    </div>
  );
}
