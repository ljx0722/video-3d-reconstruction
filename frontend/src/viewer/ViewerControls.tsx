import type { Job } from '../types';

interface Props {
  job: Job;
}

export default function ViewerControls({ job }: Props) {
  return (
    <div className="absolute top-4 left-4 bg-gray-900/80 backdrop-blur rounded-lg p-3 text-xs space-y-1 z-10 select-none">
      <p><span className="text-gray-500">作业ID：</span>{job.id.slice(0, 8)}...</p>
      {job.num_frames && <p><span className="text-gray-500">帧数：</span>{job.num_frames}</p>}
      {job.num_points && <p><span className="text-gray-500">点数：</span>{(job.num_points / 10000).toFixed(0)} 万</p>}
      {job.processing_time_secs && <p><span className="text-gray-500">耗时：</span>{job.processing_time_secs.toFixed(1)} 秒</p>}
      <p className="text-gray-500 text-[10px] pt-1 border-t border-gray-800">鼠标拖拽旋转 · 滚轮缩放 · 右键平移</p>
    </div>
  );
}
